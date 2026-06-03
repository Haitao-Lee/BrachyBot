# OpenCode Feature Analysis for BrachyBot

## Overview

Analyzed [OpenCode](https://github.com/anomalyco/opencode) (168k stars) to identify features useful for BrachyBot.

## Features Worth Integrating

### 1. ✅ Web Search (Already Integrated)
- Multi-provider support (Exa, Parallel)
- Year awareness for recent queries
- Live crawling modes
- **Status**: Already integrated in web_access module

### 2. ✅ Web Fetch with Markdown Conversion (Already Integrated)
- HTML to Markdown conversion
- Multiple format support (text, markdown, html)
- **Status**: Already integrated with improved HTML parsing

### 3. 🔄 Retry Logic with Exponential Backoff
**File**: `session/retry.ts`

**Key features**:
- Exponential backoff with configurable parameters
- Retry-After header support
- Max delay caps
- Provider-specific retry logic

**Use case**: When LLM API calls fail (rate limits, timeouts)

**Integration difficulty**: Low - standalone logic

**Recommendation**: ✅ Integrate - improves reliability

### 4. 🔄 Snapshot/Undo System
**File**: `snapshot/index.ts`

**Key features**:
- Git-based file change tracking
- Automatic snapshots before modifications
- Restore to any previous state
- Diff generation

**Use case**: Undo treatment plan changes, revert code modifications

**Integration difficulty**: Medium - requires git integration

**Recommendation**: ⚠️ Consider - useful for plan versioning

### 5. 🔄 Task Tool (Background Execution)
**File**: `tool/task.ts`

**Key features**:
- Run tasks in background
- Session-based task tracking
- Progress notifications
- Resume capability

**Use case**: Long-running operations (segmentation, dose calculation)

**Integration difficulty**: Medium - requires session management

**Recommendation**: ✅ Integrate - improves UX for long tasks

### 6. 🔄 Repository Clone & Overview
**Files**: `tool/repo_clone.ts`, `tool/repo_overview.ts`

**Key features**:
- Clone repos to managed cache
- Get repository structure overview
- Search within cloned repos

**Use case**: Research code examples, find implementation references

**Integration difficulty**: Low - uses existing git capabilities

**Recommendation**: ✅ Integrate - useful for code research

### 7. 🔄 Skill Discovery System
**File**: `skill/discovery.ts`

**Key features**:
- Download skills from URLs
- Skill caching
- Skill indexing

**Use case**: Load custom skills dynamically

**Integration difficulty**: Low - file-based system

**Recommendation**: ⚠️ Consider - already have skill system

### 8. 🔄 Image Auto-Resize
**File**: `image/image.ts`

**Key features**:
- Auto-resize large images
- Quality optimization
- Dimension limits
- Format conversion

**Use case**: Optimize CT images for LLM processing

**Integration difficulty**: Low - standalone utility

**Recommendation**: ✅ Integrate - improves image handling

## Features NOT Worth Integrating

### ❌ TypeScript/Effect-based Architecture
- BrachyBot is Python-based
- Would require complete rewrite

### ❌ Complex Permission System
- BrachyBot has simpler use case
- Overkill for medical tool

### ❌ LSP Integration
- Not relevant for BrachyBot's use case

### ❌ Desktop App Support
- BrachyBot is web-based

## Integration Priority

| Priority | Feature | Benefit |
|----------|---------|---------|
| 1 | Retry Logic | Reliability |
| 2 | Task Tool | UX for long operations |
| 3 | Repo Clone | Code research |
| 4 | Image Resize | Image optimization |
| 5 | Snapshot/Undo | Plan versioning |

## Implementation Notes

### Retry Logic
```python
# Simple exponential backoff
def retry_with_backoff(func, max_retries=3, initial_delay=1):
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = initial_delay * (2 ** attempt)
            time.sleep(delay)
```

### Task Tool
```python
# Background task execution
class BackgroundTask:
    def __init__(self, task_id, func, args):
        self.task_id = task_id
        self.thread = threading.Thread(target=self._run)
        
    def _run(self):
        # Execute task in background
        # Store result
        # Notify completion
```

### Image Resize
```python
# Auto-resize for LLM
def auto_resize(image, max_width=2000, max_height=2000):
    if image.width > max_width or image.height > max_height:
        ratio = min(max_width/image.width, max_height/image.height)
        return image.resize((int(image.width*ratio), int(image.height*ratio)))
    return image
```

## Conclusion

OpenCode has several useful features that can improve BrachyBot:
1. **Retry logic** - Most impactful for reliability
2. **Task tool** - Best for UX improvement
3. **Image resize** - Easy win for image handling

These can be integrated without major architectural changes.
