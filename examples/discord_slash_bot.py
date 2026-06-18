#!/usr/bin/env python3
"""Minimal Discord slash-command music bot powered by Veloura.

Install:

    pip install "veloura-audio[all]"

Run:

    DISCORD_TOKEN="your-bot-token" DISCORD_GUILD_ID="your-test-server-id" \
        python examples/discord_slash_bot.py

Invite the bot with the `bot` and `applications.commands` scopes, plus Connect
and Speak permissions for voice channels.

`DISCORD_GUILD_ID` is optional, but useful while testing because guild command
sync is much faster than global slash-command sync.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import discord
    from discord import app_commands
    from discord.ext import commands
except ImportError as exc:  # pragma: no cover - example dependency guard
    raise SystemExit('Install Discord support with: pip install "veloura-audio[all]"') from exc

from veloura.audio import CrossfadeAudioSource, FileAnalysisCache, resolve_stream_track, transition_preset


TOKEN_ENV = "DISCORD_TOKEN"
GUILD_ENV = "DISCORD_GUILD_ID"
PRESET_ENV = "VELOURA_PRESET"
VOLUME_ENV = "VELOURA_VOLUME"
DJ_ROLE_ENV = "VELOURA_DJ_ROLE_ID"
MAX_QUEUE_ENV = "VELOURA_MAX_QUEUE_SIZE"
PLAY_COOLDOWN_ENV = "VELOURA_PLAY_COOLDOWN_SECONDS"
RESOLVE_TIMEOUT_ENV = "VELOURA_RESOLVE_TIMEOUT_SECONDS"
CACHE_MAX_ENTRIES_ENV = "VELOURA_CACHE_MAX_ENTRIES"
CACHE_TTL_ENV = "VELOURA_CACHE_TTL_SECONDS"

ALLOWED_MENTIONS = discord.AllowedMentions.none()


def getenv_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def getenv_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"{name} must be a numeric Discord ID.")


def getenv_int_default(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


PRESET_NAME = os.getenv(PRESET_ENV, "streamer")
CONFIG = transition_preset(PRESET_NAME)
DEFAULT_VOLUME = max(0.0, min(1.5, getenv_float(VOLUME_ENV, 0.65)))
GUILD_ID = getenv_int(GUILD_ENV)
DJ_ROLE_ID = getenv_int(DJ_ROLE_ENV)
MAX_QUEUE_SIZE = max(1, min(500, getenv_int_default(MAX_QUEUE_ENV, 50)))
PLAY_COOLDOWN_SECONDS = max(0.0, min(60.0, getenv_float(PLAY_COOLDOWN_ENV, 5.0)))
RESOLVE_TIMEOUT_SECONDS = max(5.0, min(120.0, getenv_float(RESOLVE_TIMEOUT_ENV, 35.0)))
CACHE_MAX_ENTRIES = max(1, min(10_000, getenv_int_default(CACHE_MAX_ENTRIES_ENV, 1000)))
CACHE_TTL_SECONDS = max(60.0, getenv_float(CACHE_TTL_ENV, 7 * 24 * 60 * 60))
CACHE = FileAnalysisCache(
    os.getenv("VELOURA_CACHE_DIR") or None,
    max_entries=CACHE_MAX_ENTRIES,
    ttl_seconds=CACHE_TTL_SECONDS,
)


@dataclass
class GuildAudioState:
    volume: float = DEFAULT_VOLUME
    crossfade_seconds: float = CONFIG.base_crossfade_seconds
    source: CrossfadeAudioSource = field(default_factory=lambda: make_source(DEFAULT_VOLUME))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_play_at: dict[int, float] = field(default_factory=dict)
    last_error: str = ""

    def reset_source(self) -> None:
        self.source = make_source(self.volume, self.crossfade_seconds)


def make_source(volume: float, crossfade_seconds: float | None = None) -> CrossfadeAudioSource:
    return CrossfadeAudioSource(
        volume=volume,
        crossfade_seconds=CONFIG.base_crossfade_seconds if crossfade_seconds is None else crossfade_seconds,
        max_queue_size=MAX_QUEUE_SIZE,
    )


class VelouraSlashBot(commands.Bot):
    async def setup_hook(self) -> None:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Synced %s slash commands to guild %s.", len(synced), GUILD_ID)
            return

        synced = await self.tree.sync()
        logging.info("Synced %s global slash commands.", len(synced))


intents = discord.Intents.default()
bot = VelouraSlashBot(command_prefix="!", intents=intents)
players: dict[int, GuildAudioState] = {}


def state_for(guild_id: int) -> GuildAudioState:
    state = players.get(guild_id)
    if state is None:
        state = GuildAudioState()
        players[guild_id] = state
    return state


def playback_after(guild_id: int):
    def after(error: Exception | None) -> None:
        state = players.get(guild_id)
        if not state:
            return
        snapshot = state.source.snapshot()
        if error:
            state.last_error = str(error)
        elif snapshot.get("error"):
            state.last_error = str(snapshot["error"])

    return after


def clean_text(value: object, *, limit: int = 180) -> str:
    text = str(value or "")
    text = discord.utils.escape_mentions(text)
    text = discord.utils.escape_markdown(text)
    text = text.replace("`", "'")
    if len(text) > limit:
        return text[: limit - 1] + "..."
    return text


def member_has_dj_role(member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    if DJ_ROLE_ID is None:
        return True
    return any(role.id == DJ_ROLE_ID for role in getattr(member, "roles", ()))


def member_voice_channel(interaction: discord.Interaction) -> discord.abc.Connectable:
    if not interaction.guild:
        raise RuntimeError("Use this command inside a server.")
    if not isinstance(interaction.user, discord.Member):
        raise RuntimeError("Could not inspect your voice channel.")
    if not interaction.user.voice or not interaction.user.voice.channel:
        raise RuntimeError("Join a voice channel first.")
    return interaction.user.voice.channel


def require_same_voice(interaction: discord.Interaction) -> None:
    channel = member_voice_channel(interaction)
    if interaction.guild and interaction.guild.voice_client and interaction.guild.voice_client.is_connected():
        if interaction.guild.voice_client.channel != channel:
            raise RuntimeError("Join my current voice channel first.")


def require_dj_control(interaction: discord.Interaction) -> None:
    require_same_voice(interaction)
    if not isinstance(interaction.user, discord.Member) or not member_has_dj_role(interaction.user):
        raise RuntimeError("You need the configured DJ role for this command.")


def enforce_play_cooldown(state: GuildAudioState, user_id: int) -> None:
    if PLAY_COOLDOWN_SECONDS <= 0:
        return
    now = time.monotonic()
    last = state.last_play_at.get(user_id, 0.0)
    remaining = PLAY_COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        raise RuntimeError(f"Wait {remaining:.1f}s before queuing another track.")
    state.last_play_at[user_id] = now


async def connect_to_user_channel(interaction: discord.Interaction) -> discord.VoiceClient:
    channel = member_voice_channel(interaction)
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        if voice_client.channel != channel:
            raise RuntimeError("Join my current voice channel first.")
        return voice_client

    return await channel.connect()


def start_if_needed(voice_client: discord.VoiceClient, state: GuildAudioState, guild_id: int) -> None:
    if voice_client.is_playing() or voice_client.is_paused():
        return
    voice_client.play(state.source, after=playback_after(guild_id))


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minute:02d}:{second:02d}"
    return f"{minute}:{second:02d}"


@bot.event
async def on_ready() -> None:
    logging.info("Logged in as %s.", bot.user)


@bot.tree.command(name="play", description="Resolve and enqueue a track with Veloura transitions.")
@app_commands.describe(query="YouTube URL, direct audio URL, or search query")
async def play(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer(thinking=True)
    try:
        require_same_voice(interaction)
        if not isinstance(interaction.user, discord.Member) or not member_has_dj_role(interaction.user):
            raise RuntimeError("You need the configured DJ role to queue tracks.")
        voice_client = await connect_to_user_channel(interaction)
        if not interaction.guild:
            raise RuntimeError("Use this command inside a server.")

        state = state_for(interaction.guild.id)
        async with state.lock:
            if len(state.source.snapshot().get("queue") or []) >= MAX_QUEUE_SIZE:
                raise RuntimeError(f"Queue limit reached ({MAX_QUEUE_SIZE}).")
            enforce_play_cooldown(state, interaction.user.id)

        track = await resolve_stream_track(
            query,
            requester_id=interaction.user.id,
            transition_config=CONFIG,
            analysis_cache=CACHE,
            timeout=RESOLVE_TIMEOUT_SECONDS,
        )
        async with state.lock:
            if not voice_client.is_playing() and not voice_client.is_paused():
                state.reset_source()
            state.source.enqueue(track)
            start_if_needed(voice_client, state, interaction.guild.id)

        await interaction.followup.send(
            f"Queued **{clean_text(track.title)}**",
            allowed_mentions=ALLOWED_MENTIONS,
        )
    except Exception as exc:
        await interaction.followup.send(
            f"Could not queue track: `{clean_text(exc)}`",
            ephemeral=True,
            allowed_mentions=ALLOWED_MENTIONS,
        )


@bot.tree.command(name="queue", description="Show the current Veloura queue.")
async def queue_command(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return

    state = state_for(interaction.guild.id)
    snapshot = state.source.snapshot()
    current = clean_text(snapshot.get("current") or "Nothing playing")
    queued = list(snapshot.get("queue") or [])
    lines = [f"Now: **{current}**"]
    if queued:
        lines.append("Up next:")
        lines.extend(f"{index}. {clean_text(title)}" for index, title in enumerate(queued[:10], start=1))
    else:
        lines.append("Queue is empty.")

    error = snapshot.get("error") or state.last_error
    if error:
        lines.append(f"Last audio warning: `{clean_text(error)}`")

    await interaction.response.send_message("\n".join(lines), allowed_mentions=ALLOWED_MENTIONS)


@bot.tree.command(name="now", description="Show current playback state.")
async def now(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return

    state = state_for(interaction.guild.id)
    snapshot = state.source.snapshot()
    current = clean_text(snapshot.get("current") or "Nothing playing")
    elapsed = format_seconds(float(snapshot.get("elapsed") or 0.0))
    duration = format_seconds(float(snapshot.get("duration") or 0.0))
    await interaction.response.send_message(
        f"Now: **{current}**\nElapsed: `{elapsed}` / `{duration}`\n"
        f"Crossfade: `{snapshot.get('crossfade', 0):.2f}s`",
        allowed_mentions=ALLOWED_MENTIONS,
    )


@bot.tree.command(name="skip", description="Skip the current track.")
async def skip(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return

    try:
        require_dj_control(interaction)
    except Exception as exc:
        await interaction.response.send_message(f"`{clean_text(exc)}`", ephemeral=True, allowed_mentions=ALLOWED_MENTIONS)
        return

    state = state_for(interaction.guild.id)
    skipped = state.source.skip()
    await interaction.response.send_message("Skipped." if skipped else "Nothing to skip.", allowed_mentions=ALLOWED_MENTIONS)


@bot.tree.command(name="stop", description="Stop playback, clear queue, and disconnect.")
async def stop(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return

    try:
        require_dj_control(interaction)
    except Exception as exc:
        await interaction.response.send_message(f"`{clean_text(exc)}`", ephemeral=True, allowed_mentions=ALLOWED_MENTIONS)
        return

    state = state_for(interaction.guild.id)
    state.source.stop()
    state.reset_source()
    voice_client = interaction.guild.voice_client
    if voice_client:
        voice_client.stop()
        await voice_client.disconnect(force=False)
    await interaction.response.send_message("Stopped and cleared the queue.", allowed_mentions=ALLOWED_MENTIONS)


@bot.tree.command(name="volume", description="Set Veloura playback volume from 0.0 to 1.5.")
@app_commands.describe(level="Volume level. 0.65 is a safe default.")
async def volume(interaction: discord.Interaction, level: float) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return

    try:
        require_dj_control(interaction)
    except Exception as exc:
        await interaction.response.send_message(f"`{clean_text(exc)}`", ephemeral=True, allowed_mentions=ALLOWED_MENTIONS)
        return

    state = state_for(interaction.guild.id)
    state.volume = max(0.0, min(1.5, float(level)))
    state.source.set_volume(state.volume)
    await interaction.response.send_message(f"Volume set to `{state.volume:.2f}`.", allowed_mentions=ALLOWED_MENTIONS)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    token = os.getenv(TOKEN_ENV)
    if not token:
        raise SystemExit(f"Set {TOKEN_ENV} to your Discord bot token.")
    bot.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
