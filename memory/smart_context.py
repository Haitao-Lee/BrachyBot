"""
Smart Context Manager for BrachyBot
====================================
Implements intelligent context management inspired by ChatGPT, Claude, and Gemini.

Features:
1. Timestamped messages with importance scoring
2. Semantic relevance scoring for context selection
3. Entity tracking (patients, plans, doses, organs)
4. Topic tracking and transitions
5. Smart context window management
6. Conversation summarization with key facts preservation
"""

import json
import time
import re
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A conversation message with rich metadata."""
    id: str
    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: float  # Unix timestamp
    importance: float = 0.5  # 0.0 to 1.0
    relevance: float = 0.5  # 0.0 to 1.0 (computed dynamically)
    entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    token_estimate: int = 0
    is_summary: bool = False
    summarized_from: List[str] = field(default_factory=list)

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.timestamp) / 60

    @property
    def age_hours(self) -> float:
        return self.age_minutes / 60

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "importance": self.importance,
            "entities": self.entities,
            "topics": self.topics,
            "token_estimate": self.token_estimate,
            "is_summary": self.is_summary,
        }


@dataclass
class Entity:
    """An entity mentioned in the conversation."""
    name: str
    entity_type: str  # "patient", "organ", "dose", "plan", "tool", "protocol"
    first_mentioned: float  # timestamp
    last_mentioned: float  # timestamp
    mention_count: int = 1
    related_entities: List[str] = field(default_factory=list)
    context_snippets: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "entity_type": self.entity_type,
            "first_mentioned": self.first_mentioned,
            "last_mentioned": self.last_mentioned,
            "mention_count": self.mention_count,
            "related_entities": self.related_entities,
        }


@dataclass
class Topic:
    """A conversation topic with transitions."""
    name: str
    keywords: List[str]
    first_mentioned: float
    last_mentioned: float
    message_count: int = 1
    is_active: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "keywords": self.keywords,
            "first_mentioned": self.first_mentioned,
            "last_mentioned": self.last_mentioned,
            "message_count": self.message_count,
            "is_active": self.is_active,
        }


class SmartContextManager:
    """
    Intelligent context management system.

    Key principles:
    1. Not all messages are equal - some are more important
    2. Recent messages are usually more relevant
    3. Entity mentions create threads that should be tracked
    4. Topics evolve and transition
    5. Context should be compressed intelligently, not just truncated
    """

    # Entity patterns for extraction
    ENTITY_PATTERNS = {
        "dose": [
            r'\b(\d+\.?\d*)\s*(Gy|cGy|Gray)\b',
            r'\b(V\d+|D\d+|D\d+cc)\b',
            r'\b(I-125|Pd-103|Ir-192|Cs-137)\b',
        ],
        "organ": [
            r'\b(prostate|rectum|bladder|urethra|seminal vesicles?|penile bulb)\b',
            r'\b(cervix|uterus|ovary|vagina|parametrium)\b',
            r'\b(liver|lung|kidney|pancreas|spinal cord|brain)\b',
        ],
        "metric": [
            r'\b(V100|V150|V200|D90|D100|D2cc|D1cc|D0\.1cc)\b',
            r'\b(HI|CI|EI|CN|HI)\b',  # Homogeneity, Conformity, External, Conformation
        ],
        "tool": [
            r'\b(ctv_segmentation|oar_segmentation|seed_planning|dose_engine)\b',
            r'\b(clinical_kb|case_memory|plan_comparator|safety_validator)\b',
        ],
        "protocol": [
            r'\b(LDR|HDR|PDR|SBRT)\b',
            r'\b(ABS|GEC-ESTRO|NCRP|AAPM|ICRU|TG-43|TG-137)\b',
        ],
    }

    # Topic keywords for classification
    TOPIC_KEYWORDS = {
        "dose_planning": ["dose", "prescription", "plan", "coverage", "V100", "D90"],
        "segmentation": ["segment", "contour", "CTV", "GTV", "OAR", "delineate"],
        "evaluation": ["evaluate", "DVH", "constraint", "tolerance", "compliance"],
        "clinical_knowledge": ["guideline", "protocol", "recommendation", "evidence"],
        "case_management": ["save", "retrieve", "search", "case", "history"],
        "reporting": ["report", "export", "summary", "generate"],
        "safety": ["safety", "constraint", "limit", "violation", "check"],
    }

    def __init__(self, max_context_tokens: int = 8000):
        self.messages: List[Message] = []
        self.entities: Dict[str, Entity] = {}
        self.topics: Dict[str, Topic] = {}
        self.max_context_tokens = max_context_tokens
        self.current_topic: Optional[str] = None
        self._message_counter = 0

    def _generate_id(self) -> str:
        self._message_counter += 1
        return f"msg_{self._message_counter}_{int(time.time())}"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough: 1 token ≈ 4 chars)."""
        return len(text) // 4

    def _extract_entities(self, text: str) -> List[str]:
        """Extract entities from text using pattern matching."""
        entities = []
        text_lower = text.lower()

        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        entities.extend(match)
                    else:
                        entities.append(match)

        return list(set(entities))

    def _detect_topics(self, text: str) -> List[str]:
        """Detect topics from text using keyword matching."""
        topics = []
        text_lower = text.lower()

        for topic, keywords in self.TOPIC_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                topics.append(topic)

        return topics

    def _calculate_importance(self, role: str, content: str, entities: List[str]) -> float:
        """Calculate message importance score."""
        importance = 0.5  # Base importance

        # Role-based importance
        if role == "user":
            importance += 0.1  # User messages slightly more important
        elif role == "system":
            importance += 0.2  # System messages very important
        elif role == "tool":
            importance -= 0.1  # Tool results slightly less important

        # Content-based importance
        content_lower = content.lower()

        # Questions are important
        if "?" in content:
            importance += 0.1

        # Clinical values are important
        if re.search(r'\d+\.?\d*\s*(Gy|cGy|%)', content):
            importance += 0.15

        # Entity density is important
        if len(entities) > 3:
            importance += 0.1

        # Error messages are important
        if any(kw in content_lower for kw in ["error", "fail", "warning", "critical"]):
            importance += 0.2

        # Summaries are important
        if any(kw in content_lower for kw in ["summary", "conclusion", "recommendation"]):
            importance += 0.15

        return min(1.0, max(0.0, importance))

    def _calculate_relevance(self, message: Message, current_query: str,
                             current_entities: List[str], current_topics: List[str]) -> float:
        """Calculate how relevant a message is to the current query."""
        relevance = 0.0

        # Recency factor (exponential decay)
        age_minutes = message.age_minutes
        recency = max(0.1, 1.0 / (1.0 + age_minutes / 30))  # 30-minute half-life
        relevance += recency * 0.3

        # Entity overlap
        msg_entities = set(message.entities)
        curr_entities = set(current_entities)
        if msg_entities and curr_entities:
            entity_overlap = len(msg_entities & curr_entities) / max(len(msg_entities | curr_entities), 1)
            relevance += entity_overlap * 0.4

        # Topic overlap
        msg_topics = set(message.topics)
        curr_topics = set(current_topics)
        if msg_topics and curr_topics:
            topic_overlap = len(msg_topics & curr_topics) / max(len(msg_topics | curr_topics), 1)
            relevance += topic_overlap * 0.2

        # Content similarity (simple keyword matching)
        msg_words = set(message.content.lower().split())
        query_words = set(current_query.lower().split())
        if msg_words and query_words:
            word_overlap = len(msg_words & query_words) / max(len(msg_words | query_words), 1)
            relevance += word_overlap * 0.1

        return min(1.0, relevance)

    def add_message(self, role: str, content: str) -> Message:
        """Add a message to the conversation with metadata extraction."""
        # Log for debugging
        logger.debug(f"SmartContext.add_message: role={role}, content_len={len(content)}, total_messages={len(self.messages)}")

        # Extract entities and topics
        entities = self._extract_entities(content)
        topics = self._detect_topics(content)

        # Calculate importance
        importance = self._calculate_importance(role, content, entities)

        # Create message
        message = Message(
            id=self._generate_id(),
            role=role,
            content=content,
            timestamp=time.time(),
            importance=importance,
            entities=entities,
            topics=topics,
            token_estimate=self._estimate_tokens(content),
        )

        self.messages.append(message)

        # Update entity tracking
        self._update_entities(entities, content)

        # Update topic tracking
        self._update_topics(topics)

        return message

    def _update_entities(self, entities: List[str], context: str):
        """Update entity tracking."""
        now = time.time()

        for entity_name in entities:
            entity_key = entity_name.lower()

            # Determine entity type
            entity_type = "unknown"
            for etype, patterns in self.ENTITY_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, entity_name, re.IGNORECASE):
                        entity_type = etype
                        break

            if entity_key in self.entities:
                entity = self.entities[entity_key]
                entity.last_mentioned = now
                entity.mention_count += 1
                if len(entity.context_snippets) < 5:
                    entity.context_snippets.append(context[:200])
            else:
                self.entities[entity_key] = Entity(
                    name=entity_name,
                    entity_type=entity_type,
                    first_mentioned=now,
                    last_mentioned=now,
                    context_snippets=[context[:200]],
                )

    def _update_topics(self, topics: List[str]):
        """Update topic tracking."""
        now = time.time()

        for topic_name in topics:
            if topic_name in self.topics:
                topic = self.topics[topic_name]
                topic.last_mentioned = now
                topic.message_count += 1
                topic.is_active = True
            else:
                self.topics[topic_name] = Topic(
                    name=topic_name,
                    keywords=self.TOPIC_KEYWORDS.get(topic_name, []),
                    first_mentioned=now,
                    last_mentioned=now,
                )

        # Deactivate old topics
        for topic_name, topic in self.topics.items():
            if topic_name not in topics:
                if now - topic.last_mentioned > 300:  # 5 minutes
                    topic.is_active = False

    def get_relevant_context(self, current_query: str, max_tokens: int = None) -> List[Dict]:
        """
        Get context messages relevant to the current query.

        Uses intelligent selection:
        1. Always include recent messages (recency bias)
        2. Include messages with entity overlap
        3. Include messages with topic overlap
        4. Include high-importance messages
        5. Respect token budget
        """
        if max_tokens is None:
            max_tokens = self.max_context_tokens

        # If no messages, return empty
        if not self.messages:
            return []

        # Extract entities and topics from current query
        current_entities = self._extract_entities(current_query)
        current_topics = self._detect_topics(current_query)

        # Calculate relevance for each message
        scored_messages = []
        for msg in self.messages:
            if msg.is_summary:
                continue  # Handle summaries separately

            relevance = self._calculate_relevance(
                msg, current_query, current_entities, current_topics
            )
            msg.relevance = relevance

            # Combined score: relevance (60%) + importance (40%)
            combined_score = relevance * 0.6 + msg.importance * 0.4
            scored_messages.append((msg, combined_score))

        # Sort by combined score (descending)
        scored_messages.sort(key=lambda x: x[1], reverse=True)

        # Select messages within token budget
        selected = []
        total_tokens = 0

        # Always include the last few messages (recency guarantee)
        recent_messages = self.messages[-3:] if len(self.messages) >= 3 else self.messages
        for msg in recent_messages:
            if msg not in [m for m, _ in selected]:
                selected.append((msg, 1.0))  # High score for recent messages
                total_tokens += msg.token_estimate

        # Add other relevant messages
        for msg, score in scored_messages:
            if msg in [m for m, _ in selected]:
                continue

            if total_tokens + msg.token_estimate > max_tokens:
                # Try to compress the message
                compressed = self._compress_message(msg, max_tokens - total_tokens)
                if compressed:
                    selected.append((compressed, score))
                    total_tokens += compressed.token_estimate
                break

            selected.append((msg, score))
            total_tokens += msg.token_estimate

        # Sort by timestamp for chronological order
        selected.sort(key=lambda x: x[0].timestamp)

        # Convert to dict format
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
                "importance": msg.importance,
                "relevance": msg.relevance,
                "entities": msg.entities,
                "topics": msg.topics,
            }
            for msg, _ in selected
        ]

    def _compress_message(self, message: Message, max_tokens: int) -> Optional[Message]:
        """Compress a message to fit within token budget."""
        if message.token_estimate <= max_tokens:
            return message

        # Calculate target length
        target_chars = max_tokens * 4

        if len(message.content) <= target_chars:
            return message

        # Compress by keeping first and last parts
        content = message.content
        if target_chars < 100:
            return None  # Too small to compress meaningfully

        # Keep first 60% and last 40%
        first_part = content[:int(target_chars * 0.6)]
        last_part = content[-int(target_chars * 0.4):]
        compressed_content = f"{first_part}\n... [compressed] ...\n{last_part}"

        return Message(
            id=message.id + "_compressed",
            role=message.role,
            content=compressed_content,
            timestamp=message.timestamp,
            importance=message.importance,
            entities=message.entities,
            topics=message.topics,
            token_estimate=self._estimate_tokens(compressed_content),
            is_summary=True,
            summarized_from=[message.id],
        )

    def get_entity_context(self, entity_name: str) -> Optional[Dict]:
        """Get context about a specific entity."""
        entity_key = entity_name.lower()
        if entity_key in self.entities:
            entity = self.entities[entity_key]
            return {
                "name": entity.name,
                "type": entity.entity_type,
                "mention_count": entity.mention_count,
                "first_mentioned": entity.first_mentioned,
                "last_mentioned": entity.last_mentioned,
                "recent_context": entity.context_snippets[-3:] if entity.context_snippets else [],
            }
        return None

    def get_active_topics(self) -> List[Dict]:
        """Get currently active topics."""
        return [
            topic.to_dict()
            for topic in self.topics.values()
            if topic.is_active
        ]

    def get_conversation_summary(self) -> Dict:
        """Get a summary of the conversation."""
        if not self.messages:
            return {"summary": "No conversation yet", "entities": [], "topics": []}

        # Get recent messages
        recent = self.messages[-10:]

        # Get active entities
        active_entities = [
            entity.to_dict()
            for entity in self.entities.values()
            if time.time() - entity.last_mentioned < 600  # Last 10 minutes
        ]

        # Get active topics
        active_topics = self.get_active_topics()

        return {
            "message_count": len(self.messages),
            "recent_messages": [
                {"role": m.role, "content": m.content[:100], "timestamp": m.timestamp}
                for m in recent
            ],
            "active_entities": active_entities,
            "active_topics": active_topics,
            "current_topic": self.current_topic,
        }

    def compact(self, keep_last: int = 10) -> List[Message]:
        """Compact old messages into summaries."""
        if len(self.messages) <= keep_last:
            return []

        # Separate old and recent messages
        old_messages = self.messages[:-keep_last]
        recent_messages = self.messages[-keep_last:]

        # Create summaries for old messages
        summaries = self._create_summaries(old_messages)

        # Replace old messages with summaries
        self.messages = summaries + recent_messages

        return summaries

    def _create_summaries(self, messages: List[Message]) -> List[Message]:
        """Create summaries for a batch of messages."""
        if not messages:
            return []

        # Group by topic
        topic_groups = defaultdict(list)
        for msg in messages:
            for topic in msg.topics:
                topic_groups[topic].append(msg)

        summaries = []
        now = time.time()

        # Create summary for each topic
        for topic, topic_messages in topic_groups.items():
            if not topic_messages:
                continue

            # Extract key information
            key_entities = set()
            key_content = []
            for msg in topic_messages:
                key_entities.update(msg.entities)
                if msg.importance > 0.6:
                    key_content.append(msg.content[:200])

            # Create summary message
            summary_content = f"[{topic.upper()}] "
            summary_content += f"Discussed {', '.join(key_entities)}. "
            if key_content:
                summary_content += f"Key points: {'; '.join(key_content[:3])}"

            summary = Message(
                id=self._generate_id(),
                role="system",
                content=summary_content,
                timestamp=now,
                importance=0.7,
                entities=list(key_entities),
                topics=[topic],
                token_estimate=self._estimate_tokens(summary_content),
                is_summary=True,
                summarized_from=[m.id for m in topic_messages],
            )
            summaries.append(summary)

        return summaries

    def clear(self):
        """Clear all context completely."""
        self.messages = []
        self.entities = {}
        self.topics = {}
        self.current_topic = None
        self._message_counter = 0
        logger.info("SmartContext cleared - all messages and entities removed")

    def to_dict(self) -> dict:
        """Export state to dictionary."""
        return {
            "messages": [m.to_dict() for m in self.messages[-50:]],  # Keep last 50
            "entities": {k: v.to_dict() for k, v in self.entities.items()},
            "topics": {k: v.to_dict() for k, v in self.topics.items()},
            "current_topic": self.current_topic,
        }

    def get_stats(self) -> dict:
        """Get context manager statistics."""
        return {
            "message_count": len(self.messages),
            "entity_count": len(self.entities),
            "topic_count": len(self.topics),
            "active_topics": sum(1 for t in self.topics.values() if t.is_active),
            "total_tokens": sum(m.token_estimate for m in self.messages),
            "avg_importance": sum(m.importance for m in self.messages) / max(len(self.messages), 1),
        }
