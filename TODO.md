# Global Search (TOC/Sidebar)

## 1. Sidebar title filter
- Search input in sidebar header filters TOC rows by title/project name
- Pure client-side, instant
- Good for "which conversation was about X?"

## 2. Pre-built search index
- During `-a` rendering, extract user messages from each transcript into `index.json`
- Sidebar search queries this in-browser
- Matches show highlighted snippets below the title
- Finds conversations by content, not just title

## 3. Cross-file search with results
- Builds on option 2
- Clicking a result jumps directly to the matching turn (`file.html?toc=1#turn-5`)
- Shows "3 matches in 2 transcripts" style results

## Implementation plan
- Start with 1 + 2 combined: single search box in sidebar
- First filters by title; if no title matches, falls back to content index
- Option 3 adds deep-linking on top
