# Milon's Cogs

A couple of cogs I use for RedBot. I will probably expand it in the future at some point.
Currently includes GitHubLookup

## Installation

1. Install required libraries:
```bash
pip install PyGithub
```

2. Add the repository to your bot:
```bash
[p]repo add milon-cogs https://github.com/MilonPL/milon-cogs
```

3. Install the cog:
```bash
[p]cog install milon-cogs GitHubLookup
```

## Setup

1. First, create a GitHub Personal Access Token
2. Use the setup command:
```bash
[p]github setup
```
3. Click the Setup button and enter your GitHub token and repository (format: username/repository)
4. Enable the cog in desired channels:
```bash
[p]github channel true
```

## Commands

### Commands

- `[p]github setup`

- `[p]github channel <true/false>`
  - Enables or disables GitHub lookups in the current channel

- `[p]github status`
  - Shows current configuration:
    - Connected repository
    - Enabled channels
    - Connection status

### Usage

Once configured and enabled in a channel, users can:

- Look up files using square brackets:
  ```
  [filename.ext]        # Searches for filename.ext in any folder
  [path/to/file.ext]    # Looks up exact file path
  [filename.ext:98]     # Looks up line 98 of the file
  [filename.ext:10-15]  # Looks up lines 10-15 of the file
  ```

- Check pull requests and issues using pound sign:
  ```
  [#1234] # Shows status and details of PR or Issue #1234
  ```

## Examples

```
User: [config.py]
Bot: Shows content of config.py if found

User: [src/modules/test.cs]
Bot: Shows content of test.cs from exact path

User: [#456]
Bot: Shows PR #456 status and content
```
