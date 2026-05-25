"""
Markdown Skill Loader
=====================
Loads skills from Markdown files with YAML frontmatter.
Follows Claude Code SKILL.md pattern for portable, editable skill definitions.
"""

import os
import re
import yaml
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MarkdownSkill:
    """Skill loaded from Markdown file with YAML frontmatter."""
    name: str
    description: str
    category: str
    triggers: List[str]
    tool_sequence: List[str]
    parameters: Dict[str, Any] = field(default_factory=dict)
    success_threshold: float = 0.7
    version: str = "1.0.0"
    content: str = ""  # Markdown content (instructions)
    file_path: str = ""

    def matches_trigger(self, text: str) -> bool:
        """Check if text matches any trigger keyword."""
        text_lower = text.lower()
        return any(trigger.lower() in text_lower for trigger in self.triggers)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "triggers": self.triggers,
            "tool_sequence": self.tool_sequence,
            "parameters": self.parameters,
            "success_threshold": self.success_threshold,
            "version": self.version,
            "content": self.content,
            "file_path": self.file_path,
        }


class MarkdownSkillLoader:
    """Loads skills from Markdown files with YAML frontmatter."""

    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = os.path.join(os.path.dirname(__file__), "markdown")
        self.skills_dir = skills_dir
        self.skills: Dict[str, MarkdownSkill] = {}

    def load_all(self) -> Dict[str, MarkdownSkill]:
        """Load all skills from the markdown directory."""
        if not os.path.exists(self.skills_dir):
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return self.skills

        for filename in os.listdir(self.skills_dir):
            if filename.endswith(".md"):
                filepath = os.path.join(self.skills_dir, filename)
                try:
                    skill = self._load_skill_file(filepath)
                    if skill:
                        self.skills[skill.name] = skill
                        logger.info(f"Loaded skill: {skill.name}")
                except Exception as e:
                    logger.error(f"Failed to load skill {filename}: {e}")

        return self.skills

    def _load_skill_file(self, filepath: str) -> Optional[MarkdownSkill]:
        """Load a single skill from a Markdown file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse YAML frontmatter
        frontmatter, body = self._parse_frontmatter(content)
        if not frontmatter:
            logger.warning(f"No frontmatter found in {filepath}")
            return None

        # Extract fields
        name = frontmatter.get('name', os.path.splitext(os.path.basename(filepath))[0])
        description = frontmatter.get('description', '')
        category = frontmatter.get('category', 'general')
        triggers = frontmatter.get('triggers', [])
        tool_sequence = frontmatter.get('tool_sequence', [])
        parameters = frontmatter.get('parameters', {})
        success_threshold = frontmatter.get('success_threshold', 0.7)
        version = frontmatter.get('version', '1.0.0')

        return MarkdownSkill(
            name=name,
            description=description,
            category=category,
            triggers=triggers,
            tool_sequence=tool_sequence,
            parameters=parameters,
            success_threshold=success_threshold,
            version=version,
            content=body.strip(),
            file_path=filepath,
        )

    def _parse_frontmatter(self, content: str) -> tuple:
        """Parse YAML frontmatter from Markdown content."""
        # Match frontmatter between --- markers
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
        if not match:
            return None, content

        yaml_content = match.group(1)
        body = match.group(2)

        try:
            frontmatter = yaml.safe_load(yaml_content)
            return frontmatter, body
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML frontmatter: {e}")
            return None, content

    def find_by_trigger(self, text: str) -> List[MarkdownSkill]:
        """Find skills matching trigger text."""
        matches = []
        for skill in self.skills.values():
            if skill.matches_trigger(text):
                matches.append(skill)
        return matches

    def find_by_category(self, category: str) -> List[MarkdownSkill]:
        """Find skills in a category."""
        return [s for s in self.skills.values() if s.category == category]

    def get_skill(self, name: str) -> Optional[MarkdownSkill]:
        """Get skill by name."""
        return self.skills.get(name)

    def reload(self):
        """Reload all skills from disk."""
        self.skills.clear()
        self.load_all()


# Global loader instance
_loader: Optional[MarkdownSkillLoader] = None


def get_skill_loader() -> MarkdownSkillLoader:
    """Get the global skill loader instance."""
    global _loader
    if _loader is None:
        _loader = MarkdownSkillLoader()
        _loader.load_all()
    return _loader


def find_skill_for_request(text: str) -> Optional[MarkdownSkill]:
    """Find the best matching skill for a user request."""
    loader = get_skill_loader()
    matches = loader.find_by_trigger(text)

    if not matches:
        return None

    # Return the skill with the most matching triggers
    best = max(matches, key=lambda s: sum(1 for t in s.triggers if t.lower() in text.lower()))
    return best
