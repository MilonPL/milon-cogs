import discord
import re
import asyncio
from typing import List, Tuple
from github import Github, Auth
from github.GithubException import GithubException
from github.ContentFile import ContentFile
from datetime import datetime
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box
from discord.ui import Modal, TextInput


class GitHubSetupModal(Modal, title='GitHub Integration Setup'):
    token = TextInput(
        label='GitHub Token',
        placeholder='Your GitHub personal access token',
        required=True
    )
    repository = TextInput(
        label='Repository',
        placeholder='username/repository',
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Processing...", ephemeral=True)
        self.stop()


class SetupButton(discord.ui.View):
    def __init__(self, member):
        self.member = member
        super().__init__()
        self.modal = None

    @discord.ui.button(label='Setup', style=discord.ButtonStyle.green)
    async def setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.member != interaction.user:
            return await interaction.response.send_message("You cannot use this.", ephemeral=True)

        self.modal = GitHubSetupModal()
        await interaction.response.send_modal(self.modal)
        await self.modal.wait()
        self.stop()


class GitHubLookup(commands.Cog):
    """Look up GitHub files and PRs directly in Discord"""

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "servers": {},
            "enabled_channels": []
        }
        self.config.register_guild(**default_guild)
        self.gh_instances = {}
        self.search_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        """Initialize GitHub instances for all configured guilds on load"""
        for guild in self.bot.guilds:
            servers = await self.config.guild(guild).servers()
            for server_name, server_data in servers.items():
                try:
                    auth = Auth.Token(server_data['token'])
                    gh = Github(auth=auth)
                    repo_instance = gh.get_repo(server_data['repository'])
                    self.gh_instances[guild.id] = {
                        "client": gh,
                        "repo": repo_instance
                    }
                except Exception:
                    continue

    async def cog_unload(self) -> None:
        """Clean up GitHub instances on unload"""
        for instance in self.gh_instances.values():
            instance["client"].close()
        self.gh_instances.clear()

    @commands.group()
    @checks.admin()
    async def github(self, ctx: commands.Context):
        """Configure GitHub integration settings"""
        pass

    @github.command()
    async def setup(self, ctx: commands.Context):
        """Set up GitHub integration for this server"""
        view = SetupButton(member=ctx.author)
        await ctx.send("To set up GitHub integration, press this button.", view=view)
        await view.wait()

        if view.modal is None:
            return

        # Store in config securely
        async with self.config.guild(ctx.guild).servers() as servers:
            servers["default"] = {
                "token": view.modal.token.value,
                "repository": view.modal.repository.value
            }

        # Initialize GitHub instance
        try:
            auth = Auth.Token(view.modal.token.value)
            gh = Github(auth=auth)
            repo = gh.get_repo(view.modal.repository.value)
            self.gh_instances[ctx.guild.id] = {
                "client": gh,
                "repo": repo
            }
            await ctx.send("✅ GitHub integration configured successfully!", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error configuring GitHub: {str(e)}", ephemeral=True)

    @github.command()
    async def channel(self, ctx: commands.Context, enabled: bool = True):
        """Enable/disable GitHub lookups in the current channel"""
        async with self.config.guild(ctx.guild).enabled_channels() as channels:
            if enabled and ctx.channel.id not in channels:
                channels.append(ctx.channel.id)
            elif not enabled and ctx.channel.id in channels:
                channels.remove(ctx.channel.id)

        status = "enabled" if enabled else "disabled"
        await ctx.send(f"GitHub lookups {status} for this channel")

    @github.command()
    async def status(self, ctx: commands.Context):
        """Show the current GitHub integration status"""
        servers = await self.config.guild(ctx.guild).servers()
        enabled_channels = await self.config.guild(ctx.guild).enabled_channels()

        if not servers:
            await ctx.send("❌ GitHub integration is not configured for this server.")
            return

        embed = discord.Embed(
            title="GitHub Integration Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        # Show repository info
        repo_info = servers.get("default", {})
        if repo_info:
            embed.add_field(
                name="Repository",
                value=f"`{repo_info['repository']}`",
                inline=False
            )

        # Show enabled channels
        if enabled_channels:
            channel_mentions = [f"<#{channel_id}>" for channel_id in enabled_channels]
            embed.add_field(
                name="Enabled Channels",
                value="\n".join(channel_mentions) or "None",
                inline=False
            )
        else:
            embed.add_field(
                name="Enabled Channels",
                value="No channels enabled",
                inline=False
            )

        # Test connection
        if ctx.guild.id in self.gh_instances:
            embed.add_field(
                name="Connection Status",
                value="✅ Connected",
                inline=False
            )
        else:
            embed.add_field(
                name="Connection Status",
                value="❌ Not connected",
                inline=False
            )

        await ctx.send(embed=embed)

    async def find_matching_files(self, repo, filename: str) -> List[Tuple[str, ContentFile]]:
        """Find all files matching the given filename in the repository"""
        async with self.search_lock:  # Prevent multiple simultaneous searches
            matches = []
            loop = asyncio.get_running_loop()

            try:
                # First try direct path
                content = await loop.run_in_executor(
                    None,
                    lambda: repo.get_contents(filename)
                )
                if not isinstance(content, list):
                    matches.append((filename, content))
                    return matches
            except GithubException:
                pass

            if '/' in filename:  # If path is specified, don't do full search
                return matches

            # Use recursive tree search
            try:
                tree = await loop.run_in_executor(
                    None,
                    lambda: repo.get_git_tree(repo.default_branch, recursive=True)
                )

                for item in tree.tree:
                    if item.type == 'blob' and item.path.endswith(filename):
                        try:
                            content = await loop.run_in_executor(
                                None,
                                lambda: repo.get_contents(item.path)
                            )
                            matches.append((item.path, content))
                        except GithubException:
                            continue

            except GithubException as e:
                print(f"Search error: {e}")

            return matches

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        enabled_channels = await self.config.guild(message.guild).enabled_channels()
        if message.channel.id not in enabled_channels:
            return

        gh_data = self.gh_instances.get(message.guild.id)
        if not gh_data:
            return

        repo = gh_data["repo"]

        # Look for file references [filename.cs]
        file_matches = re.findall(r'\[(.*?)]', message.content)
        for filename in file_matches:
            if filename.startswith('#'):  # Skip PR references
                continue

            try:
                async with message.channel.typing():  # Show typing indicator while searching
                    matches = await self.find_matching_files(repo, filename)

                if not matches:
                    embed = discord.Embed(
                        title="❌ File Not Found",
                        description=f"Could not find file '{filename}' in the repository.",
                        color=discord.Color.red()
                    )
                    await message.channel.send(embed=embed)
                    continue

                if len(matches) > 1 and not '/' in filename:
                    # Multiple matches found, show paths
                    embed = discord.Embed(
                        title="Multiple Files Found",
                        description="Please specify the full path to one of these files:",
                        color=discord.Color.gold()
                    )
                    for path, content in matches[:10]:  # Limit to 10 results
                        embed.add_field(
                            name=path,
                            value=f"[View on GitHub]({content.html_url})",
                            inline=False
                        )
                    if len(matches) > 10:
                        embed.description += f"\n\nShowing 10 of {len(matches)} matches"
                    await message.channel.send(embed=embed)
                    continue

                # Get the matching file
                if '/' in filename:
                    # If path specified, find exact match
                    match = next((m for m in matches if m[0] == filename), None)
                else:
                    # If no path specified and only one match, use it
                    match = matches[0] if len(matches) == 1 else None

                if not match:
                    embed = discord.Embed(
                        title="❌ File Not Found",
                        description=f"Could not find exact file '{filename}' in the repository.",
                        color=discord.Color.red()
                    )
                    await message.channel.send(embed=embed)
                    continue

                path, content = match
                file_content = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: content.decoded_content.decode()
                )

                # Truncate content if too long
                if len(file_content) > 2000:
                    file_content = file_content[:1900] + "\n\n... (content truncated)"

                embed = discord.Embed(
                    title=f"📄 {path}",
                    description=box(file_content, lang=path.split('.')[-1]),
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(
                    name="View on GitHub",
                    value=f"[View full file]({content.html_url})",
                    inline=False
                )
                await message.channel.send(embed=embed)

            except Exception as e:
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"An error occurred: {str(e)}",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed)

        # Look for PR references [#1234]
        pr_matches = re.findall(r'\[#(\d+)]', message.content)
        for pr_number in pr_matches:
            try:
                pr = repo.get_pull(int(pr_number))

                embed = discord.Embed(
                    title=f"#{pr.number} {pr.title}",
                    description=pr.body[:1000] if pr.body else "No description provided",
                    color=discord.Color.green() if pr.state == "open" else discord.Color.red(),
                    url=pr.html_url,
                    timestamp=pr.created_at
                )

                if pr.body and len(pr.body) > 1000:
                    embed.description += "\n\n... (description truncated)"

                embed.add_field(name="Status", value=pr.state.capitalize(), inline=True)
                embed.add_field(name="Author", value=pr.user.login, inline=True)
                embed.add_field(name="Comments", value=str(pr.comments), inline=True)

                if pr.merged:
                    embed.add_field(name="Merged", value="Yes", inline=True)
                    embed.add_field(name="Merged by", value=pr.merged_by.login, inline=True)

                await message.channel.send(embed=embed)

            except Exception as e:
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"Error accessing PR #{pr_number}: {str(e)}",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed)
