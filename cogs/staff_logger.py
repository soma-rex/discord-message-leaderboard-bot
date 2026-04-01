from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands, tasks


EVENT_EMOJI = "<:eventcard:1488562862262718708>"
GIVEAWAY_EMOJI = "<:giveaway:1488562864926101637>"
MOD_EMOJI = "<:mod:1488568750671269989>"

REPORT_CHANNEL_ID = 1181356533557239818
MOD_ACTIVITY_CHANNEL_ID = 1013340674805993512
MOD_MESSAGE_COOLDOWN_SECONDS = 8

GIVEAWAY_MANAGER_ROLE_ID = 996372025486622760
EVENT_MANAGER_ROLE_ID = 996372072961937450
MODERATOR_ROLE_ID = 996371883807219803
TRIAL_MODERATOR_ROLE_ID = 996371928493330534
TOUCHING_GRASS_ROLE_ID = 1128285153135955978
BASIC_STAFF_ROLE_ID = 996372307528384583
SOTM_ROLE_ID = 1134767539356962917

GMAN_TRIGGER_ROLE_IDS = {
    1107542167746007080,
    996367555323248690,
    1152283755336183828,
}
EMAN_TRIGGER_ROLE_IDS = {996367564508758026}

PING_REQUIREMENT = 7
MOD_MESSAGE_REQUIREMENT = 200
TRIAL_MOD_MESSAGE_REQUIREMENT = 250

ROLE_PRIORITY = (
    ("gman", GIVEAWAY_MANAGER_ROLE_ID),
    ("eman", EVENT_MANAGER_ROLE_ID),
    ("mod", MODERATOR_ROLE_ID),
    ("tmod", TRIAL_MODERATOR_ROLE_ID),
)
STAFF_ROLE_IDS = {role_id for _, role_id in ROLE_PRIORITY}
STAFF_ROLE_IDS.add(BASIC_STAFF_ROLE_ID)
STAFF_ROLE_IDS.add(TOUCHING_GRASS_ROLE_ID)
PREFIXES = (";", "&")


class StaffProgressView(discord.ui.View):
    def __init__(self, cog: "StaffLoggerCog", guild: discord.Guild, requester_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.requester_id = requester_id

    async def _swap_embed(self, interaction: discord.Interaction, role_type: str):
        embed = await self.cog._build_staff_overview_embed_filtered(self.guild, role_type)
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the command user can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Mods", style=discord.ButtonStyle.primary)
    async def mods_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._swap_embed(interaction, "mod")

    @discord.ui.button(label="Gman", style=discord.ButtonStyle.secondary)
    async def gman_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._swap_embed(interaction, "gman")

    @discord.ui.button(label="Eman", style=discord.ButtonStyle.secondary)
    async def eman_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._swap_embed(interaction, "eman")


class StaffLoggerCog(commands.Cog, name="Staff Logger"):
    staff_group = app_commands.Group(name="staff", description="Staff management commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conn: sqlite3.Connection = bot.conn
        self.cursor: sqlite3.Cursor = bot.cursor
        self.mod_message_cooldowns: dict[int, datetime] = {}
        self._ensure_tables()
        self._ensure_active_week()
        self.weekly_reset_loop.start()

    def cog_unload(self):
        self.weekly_reset_loop.cancel()

    def _ensure_tables(self):
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_users (
                user_id INTEGER PRIMARY KEY,
                role_type TEXT NOT NULL,
                is_on_break INTEGER NOT NULL DEFAULT 0,
                saved_roles TEXT,
                break_until TEXT,
                registered_at TEXT,
                birthday TEXT,
                hired_date TEXT,
                sotm_count INTEGER NOT NULL DEFAULT 0,
                total_gman_count INTEGER NOT NULL DEFAULT 0,
                total_eman_count INTEGER NOT NULL DEFAULT 0,
                total_mod_message_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.cursor.execute("PRAGMA table_info(staff_users)")
        columns = {row[1] for row in self.cursor.fetchall()}
        required_columns = {
            "break_until": "TEXT",
            "registered_at": "TEXT",
            "birthday": "TEXT",
            "hired_date": "TEXT",
            "sotm_count": "INTEGER NOT NULL DEFAULT 0",
            "total_gman_count": "INTEGER NOT NULL DEFAULT 0",
            "total_eman_count": "INTEGER NOT NULL DEFAULT 0",
            "total_mod_message_count": "INTEGER NOT NULL DEFAULT 0",
        }
        for column_name, column_type in required_columns.items():
            if column_name not in columns:
                self.cursor.execute(f"ALTER TABLE staff_users ADD COLUMN {column_name} {column_type}")
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_logs (
                user_id INTEGER NOT NULL,
                week_id TEXT NOT NULL,
                gman_count INTEGER NOT NULL DEFAULT 0,
                eman_count INTEGER NOT NULL DEFAULT 0,
                mod_message_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, week_id)
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self.conn.commit()

    def _config_get(self, key: str, default: str | None = None) -> str | None:
        self.cursor.execute("SELECT value FROM staff_config WHERE key = ?", (key,))
        row = self.cursor.fetchone()
        return row[0] if row else default

    def _config_set(self, key: str, value: str):
        self.cursor.execute(
            "INSERT OR REPLACE INTO staff_config (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def _current_week_id(self) -> str:
        now = datetime.now(timezone.utc)
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        return monday.strftime("%Y-%m-%d")

    def _week_label(self, week_id: str) -> str:
        start = datetime.strptime(week_id, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = start + timedelta(days=6)
        return f"{start.strftime('%d %b')} - {end.strftime('%d %b %Y')} UTC"

    def _ensure_active_week(self):
        active_week = self._config_get("active_week_id")
        if not active_week:
            self._config_set("active_week_id", self._current_week_id())

    def _registered_row(self, user_id: int):
        self.cursor.execute(
            """
            SELECT
                role_type,
                is_on_break,
                saved_roles,
                break_until,
                registered_at,
                birthday,
                hired_date,
                sotm_count,
                total_gman_count,
                total_eman_count,
                total_mod_message_count
            FROM staff_users
            WHERE user_id = ?
            """,
            (user_id,),
        )
        return self.cursor.fetchone()

    def _resolve_role_types(self, member: discord.Member) -> list[str]:
        role_ids = {role.id for role in member.roles}
        return [role_type for role_type, role_id in ROLE_PRIORITY if role_id in role_ids]

    def _serialize_role_types(self, role_types: list[str]) -> str:
        return ",".join(role_types)

    def _parse_role_types(self, value: str | None) -> list[str]:
        if not value:
            return []
        return [part for part in value.split(",") if part]

    def _parse_break_until(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _parse_date_string(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None

    def _format_date_string(self, value: str | None, *, unknown: str = "Not known yet") -> str:
        parsed = self._parse_date_string(value)
        if parsed is None:
            return unknown
        return parsed.strftime("%d %b %Y")

    def _mention_line(self, user_id: int, name: str) -> str:
        return f"{name} (<@{user_id}>)"

    def _requirement_for(self, role_type: str) -> int:
        if role_type in {"gman", "eman"}:
            return PING_REQUIREMENT
        if role_type == "tmod":
            return TRIAL_MOD_MESSAGE_REQUIREMENT
        return MOD_MESSAGE_REQUIREMENT

    def _count_for(self, log_row: sqlite3.Row | tuple | None, role_type: str) -> int:
        if not log_row:
            return 0
        if role_type == "gman":
            return log_row[0]
        if role_type == "eman":
            return log_row[1]
        return log_row[2]

    def _progress_bar(self, current: int, target: int, *, is_on_break: bool = False, length: int = 5) -> str:
        if is_on_break:
            return "🟦" * length
        filled = min(length, int((current / target) * length)) if target > 0 else length
        return ("🟩" * filled) + ("🟥" * (length - filled))

    def _section_title(self, role_type: str) -> str:
        mapping = {
            "gman": f"{GIVEAWAY_EMOJI} Giveaway Managers",
            "eman": f"{EVENT_EMOJI} Event Managers",
            "mod": f"{MOD_EMOJI} Moderators",
            "tmod": f"{MOD_EMOJI} Trial Moderators",
        }
        return mapping[role_type]

    def _upsert_staff_user(
        self,
        user_id: int,
        role_types: list[str],
        *,
        is_on_break: int = 0,
        saved_roles: str | None = None,
        break_until: str | None = None,
    ):
        existing = self._registered_row(user_id)
        saved_value = saved_roles if saved_roles is not None else (existing[2] if existing else None)
        break_value = is_on_break if existing is None else (existing[1] if saved_roles is None and is_on_break == 0 else is_on_break)
        break_until_value = break_until if break_until is not None else (existing[3] if existing else None)
        self.cursor.execute(
            """
            INSERT INTO staff_users (user_id, role_type, is_on_break, saved_roles, break_until)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                role_type = excluded.role_type,
                is_on_break = excluded.is_on_break,
                saved_roles = excluded.saved_roles,
                break_until = excluded.break_until
            """,
            (user_id, self._serialize_role_types(role_types), break_value, saved_value, break_until_value),
        )
        self.conn.commit()

    def _ensure_weekly_row(self, user_id: int) -> str:
        week_id = self._config_get("active_week_id", self._current_week_id())
        self.cursor.execute(
            """
            INSERT OR IGNORE INTO weekly_logs (user_id, week_id, gman_count, eman_count, mod_message_count)
            VALUES (?, ?, 0, 0, 0)
            """,
            (user_id, week_id),
        )
        self.conn.commit()
        return week_id

    def _increment_log(self, user_id: int, field_name: str):
        week_id = self._ensure_weekly_row(user_id)
        self.cursor.execute(
            f"UPDATE weekly_logs SET {field_name} = {field_name} + 1 WHERE user_id = ? AND week_id = ?",
            (user_id, week_id),
        )
        self.conn.commit()
        total_field_map = {
            "gman_count": "total_gman_count",
            "eman_count": "total_eman_count",
            "mod_message_count": "total_mod_message_count",
        }
        total_field = total_field_map.get(field_name)
        if total_field:
            self._increment_total_stat(user_id, total_field)

    def _get_weekly_log(self, user_id: int, week_id: str | None = None):
        target_week = week_id or self._config_get("active_week_id", self._current_week_id())
        self.cursor.execute(
            """
            SELECT gman_count, eman_count, mod_message_count
            FROM weekly_logs
            WHERE user_id = ? AND week_id = ?
            """,
            (user_id, target_week),
        )
        return self.cursor.fetchone()

    def _sync_member_registration(self, member: discord.Member):
        row = self._registered_row(member.id)
        if not row:
            return None
        if row[1]:
            return row

        current_roles = self._resolve_role_types(member)
        if not current_roles:
            return row
        self.cursor.execute(
            "UPDATE staff_users SET role_type = ? WHERE user_id = ?",
            (self._serialize_role_types(current_roles), member.id),
        )
        self.conn.commit()
        return self._registered_row(member.id)

    def _display_name(self, guild: discord.Guild | None, user_id: int, fallback: str | None = None) -> str:
        if guild:
            member = guild.get_member(user_id)
            if member:
                return member.display_name
        return fallback or f"User {user_id}"

    async def _display_name_fixed(self, guild: discord.Guild | None, user_id: int) -> str:
        return f"<@{user_id}>"

    def _is_registered(self, user_id: int) -> bool:
        return self._registered_row(user_id) is not None

    def _can_use_staff_commands(self, member: discord.Member) -> bool:
        return self._is_registered(member.id) or member.guild_permissions.administrator

    def _not_registered_message(self) -> str:
        return "You can't use this command because you're not registered. Use `/register` first."

    def _increment_total_stat(self, user_id: int, field_name: str):
        self.cursor.execute(f"UPDATE staff_users SET {field_name} = {field_name} + 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def _set_profile_field(self, user_id: int, field_name: str, value: str | None):
        self.cursor.execute(f"UPDATE staff_users SET {field_name} = ? WHERE user_id = ?", (value, user_id))
        self.conn.commit()

    def _build_profile_embed(self, member: discord.Member) -> discord.Embed | None:
        row = self._sync_member_registration(member)
        if not row:
            return None

        role_types = self._parse_role_types(row[0])
        is_on_break = bool(row[1])
        registered_at = row[4]
        birthday = row[5]
        hired_date = row[6]
        sotm_count = row[7] or 0
        total_gman = row[8] or 0
        total_eman = row[9] or 0
        total_mod = row[10] or 0

        embed = discord.Embed(title="Staff Profile", color=discord.Color.blurple())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Tracked Roles", value=", ".join(role.upper() for role in role_types) or "None", inline=False)
        embed.add_field(name="Date Joined", value=self._format_date_string(registered_at), inline=True)
        embed.add_field(name="Hired Date", value=self._format_date_string(hired_date), inline=True)
        embed.add_field(name="Birthday", value=self._format_date_string(birthday), inline=True)
        embed.add_field(name="On Break", value="Yes" if is_on_break else "No", inline=True)
        embed.add_field(name="SOTM Awards", value=str(sotm_count), inline=True)
        embed.add_field(name="Lifetime Stats", value=(
            f"{GIVEAWAY_EMOJI} Giveaway pings: **{total_gman}**\n"
            f"{EVENT_EMOJI} Event pings: **{total_eman}**\n"
            f"{MOD_EMOJI} Mod messages: **{total_mod}**"
        ), inline=False)
        return embed

    async def _build_staff_overview_embed(self, guild: discord.Guild) -> discord.Embed:
        active_week = self._config_get("active_week_id", self._current_week_id())
        self.cursor.execute(
            """
            SELECT user_id, role_type, is_on_break
            FROM staff_users
            ORDER BY role_type, user_id
            """
        )
        staff_rows = self.cursor.fetchall()
        self.cursor.execute(
            """
            SELECT user_id, gman_count, eman_count, mod_message_count
            FROM weekly_logs
            WHERE week_id = ?
            """,
            (active_week,),
        )
        log_map = {row[0]: row[1:] for row in self.cursor.fetchall()}

        sections: dict[str, list[str]] = {"gman": [], "eman": [], "mod": []}
        for user_id, role_type_value, is_on_break in staff_rows:
            role_types = self._parse_role_types(role_type_value)
            if not role_types:
                continue
            counts = log_map.get(user_id)
            base_label = await self._display_name_fixed(guild, user_id)

            if "gman" in role_types:
                current = self._count_for(counts, "gman")
                sections["gman"].append(
                    f"{base_label:<18} | {self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))} "
                    f"({'break' if is_on_break else f'{current}/{PING_REQUIREMENT}'})"
                )

            if "eman" in role_types:
                current = self._count_for(counts, "eman")
                sections["eman"].append(
                    f"{base_label:<18} | {self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))} "
                    f"({'break' if is_on_break else f'{current}/{PING_REQUIREMENT}'})"
                )

            if {"mod", "tmod"} & set(role_types):
                current = self._count_for(counts, "mod")
                mod_role_type = "tmod" if "tmod" in role_types and "mod" not in role_types else "mod"
                mod_requirement = self._requirement_for(mod_role_type)
                mod_label = f"{base_label} [Trial]" if mod_role_type == "tmod" else base_label
                sections["mod"].append(
                    f"{mod_label:<18} | {self._progress_bar(current, mod_requirement, is_on_break=bool(is_on_break))} "
                    f"({'break' if is_on_break else f'{current}/{mod_requirement}'})"
                )

        embed = discord.Embed(
            title="Registered Staff Progress",
            description=f"Week: **{self._week_label(active_week)}**",
            color=discord.Color.teal(),
        )
        for role_type in ("gman", "eman", "mod"):
            embed.add_field(
                name=self._section_title(role_type),
                value="\n".join(sections[role_type]) or "No registered staff",
                inline=False,
            )
        embed.set_footer(text="Registered staff only | complete | not met | break")
        return embed

    async def _build_staff_overview_embed_filtered(self, guild: discord.Guild, role_type: str) -> discord.Embed:
        active_week = self._config_get("active_week_id", self._current_week_id())
        self.cursor.execute(
            """
            SELECT user_id, role_type, is_on_break
            FROM staff_users
            ORDER BY role_type, user_id
            """
        )
        staff_rows = self.cursor.fetchall()
        self.cursor.execute(
            """
            SELECT user_id, gman_count, eman_count, mod_message_count
            FROM weekly_logs
            WHERE week_id = ?
            """,
            (active_week,),
        )
        log_map = {row[0]: row[1:] for row in self.cursor.fetchall()}

        section_lines: list[str] = []
        for user_id, role_type_value, is_on_break in staff_rows:
            role_types = self._parse_role_types(role_type_value)
            if not role_types:
                continue
            counts = log_map.get(user_id)
            base_label = await self._display_name_fixed(guild, user_id)

            if role_type == "gman" and "gman" in role_types:
                current = self._count_for(counts, "gman")
                section_lines.append(
                    f"{base_label:<18} | {self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))} "
                    f"({'break' if is_on_break else f'{current}/{PING_REQUIREMENT}'})"
                )
            elif role_type == "eman" and "eman" in role_types:
                current = self._count_for(counts, "eman")
                section_lines.append(
                    f"{base_label:<18} | {self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))} "
                    f"({'break' if is_on_break else f'{current}/{PING_REQUIREMENT}'})"
                )
            elif role_type == "mod" and {"mod", "tmod"} & set(role_types):
                current = self._count_for(counts, "mod")
                mod_role_type = "tmod" if "tmod" in role_types and "mod" not in role_types else "mod"
                mod_requirement = self._requirement_for(mod_role_type)
                mod_label = f"{base_label} [Trial]" if mod_role_type == "tmod" else base_label
                section_lines.append(
                    f"{mod_label:<18} | {self._progress_bar(current, mod_requirement, is_on_break=bool(is_on_break))} "
                    f"({'break' if is_on_break else f'{current}/{mod_requirement}'})"
                )

        embed = discord.Embed(
            title="Registered Staff Progress",
            description=f"Week: **{self._week_label(active_week)}**",
            color=discord.Color.teal(),
        )
        embed.add_field(
            name=self._section_title(role_type),
            value="\n".join(section_lines) or "No registered staff",
            inline=False,
        )
        embed.set_footer(text="Registered staff only | complete | not met | break")
        return embed

    async def _restore_expired_breaks(self):
        now = datetime.now(timezone.utc)
        self.cursor.execute(
            """
            SELECT user_id, role_type, saved_roles, break_until
            FROM staff_users
            WHERE is_on_break = 1 AND break_until IS NOT NULL
            """
        )
        rows = self.cursor.fetchall()
        for user_id, role_type_value, saved_roles, break_until_value in rows:
            break_until = self._parse_break_until(break_until_value)
            if break_until is None or break_until > now:
                continue

            restored = False
            for guild in self.bot.guilds:
                member = guild.get_member(user_id)
                if member is None:
                    continue

                restored = await self._restore_member_roles(member, saved_roles, reason="Timed staff break expired")
                break

            if restored:
                self.cursor.execute(
                    """
                    UPDATE staff_users
                    SET is_on_break = 0, saved_roles = NULL, break_until = NULL
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
        self.conn.commit()

    async def _restore_member_roles(self, member: discord.Member, saved_roles: str | None, *, reason: str) -> bool:
        break_role = member.guild.get_role(TOUCHING_GRASS_ROLE_ID)
        roles_to_add = []
        for role_id_text in (saved_roles or "").split(","):
            if not role_id_text:
                continue
            role = member.guild.get_role(int(role_id_text))
            if role is not None and role not in member.roles:
                roles_to_add.append(role)

        changed = False
        if break_role and break_role in member.roles:
            await member.remove_roles(break_role, reason=reason)
            changed = True
        if roles_to_add:
            await member.add_roles(*roles_to_add, reason=reason)
            changed = True
        return changed

    async def _send_weekly_report(self, report_week_id: str):
        channel = self.bot.get_channel(REPORT_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(REPORT_CHANNEL_ID)
            except discord.HTTPException:
                return

        guild = channel.guild if isinstance(channel, discord.TextChannel) else None
        self.cursor.execute(
            """
            SELECT user_id, role_type, is_on_break
            FROM staff_users
            ORDER BY role_type, user_id
            """
        )
        staff_rows = self.cursor.fetchall()
        self.cursor.execute(
            """
            SELECT user_id, gman_count, eman_count, mod_message_count
            FROM weekly_logs
            WHERE week_id = ?
            """,
            (report_week_id,),
        )
        log_map = {row[0]: row[1:] for row in self.cursor.fetchall()}

        sections: dict[str, list[str]] = {"gman": [], "eman": [], "mod": []}
        for user_id, role_type_value, is_on_break in staff_rows:
            role_types = self._parse_role_types(role_type_value)
            if not role_types:
                continue
            counts = log_map.get(user_id)
            base_label = await self._display_name_fixed(guild, user_id)

            if "gman" in role_types:
                current = self._count_for(counts, "gman")
                bar = self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))
                target_text = "break" if is_on_break else f"{current}/{PING_REQUIREMENT}"
                sections["gman"].append(f"{base_label:<18} | {bar} ({target_text})")

            if "eman" in role_types:
                current = self._count_for(counts, "eman")
                bar = self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))
                target_text = "break" if is_on_break else f"{current}/{PING_REQUIREMENT}"
                sections["eman"].append(f"{base_label:<18} | {bar} ({target_text})")

            if {"mod", "tmod"} & set(role_types):
                current = self._count_for(counts, "mod")
                mod_role_type = "tmod" if "tmod" in role_types and "mod" not in role_types else "mod"
                mod_requirement = self._requirement_for(mod_role_type)
                bar = self._progress_bar(current, mod_requirement, is_on_break=bool(is_on_break))
                target_text = "break" if is_on_break else f"{current}/{mod_requirement}"
                mod_label = f"{base_label} [Trial]" if mod_role_type == "tmod" else base_label
                sections["mod"].append(f"{mod_label:<18} | {bar} ({target_text})")

        embed = discord.Embed(
            title="Weekly Staff Report",
            description=f"Week: **{self._week_label(report_week_id)}**",
            color=discord.Color.dark_teal(),
        )

        for role_type in ("gman", "eman", "mod"):
            lines = sections[role_type] or ["No registered staff"]
            embed.add_field(
                name=self._section_title(role_type),
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text="complete | not met | break")
        await channel.send(embed=embed)

    async def _roll_week_if_needed(self):
        current_week = self._current_week_id()
        active_week = self._config_get("active_week_id", current_week)
        if active_week == current_week:
            return

        await self._send_weekly_report(active_week)
        self.cursor.execute("DELETE FROM weekly_logs WHERE week_id = ?", (active_week,))
        self.conn.commit()
        self._config_set("active_week_id", current_week)

    @tasks.loop(minutes=1)
    async def weekly_reset_loop(self):
        await self._restore_expired_breaks()
        await self._roll_week_if_needed()

    @weekly_reset_loop.before_loop
    async def before_weekly_reset_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        row = self._registered_row(after.id)
        if not row or row[1]:
            return
        role_types = self._resolve_role_types(after)
        if role_types:
            self._upsert_staff_user(after.id, role_types)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(PREFIXES):
            return

        row = self._sync_member_registration(message.author)
        if not row or row[1]:
            return

        role_types = set(self._parse_role_types(row[0]))
        mentioned_role_ids = {role.id for role in message.role_mentions}

        if "gman" in role_types and mentioned_role_ids & GMAN_TRIGGER_ROLE_IDS:
            self._increment_log(message.author.id, "gman_count")
        if "eman" in role_types and mentioned_role_ids & EMAN_TRIGGER_ROLE_IDS:
            self._increment_log(message.author.id, "eman_count")

        if role_types & {"mod", "tmod"} and message.channel.id == MOD_ACTIVITY_CHANNEL_ID:
            now = datetime.now(timezone.utc)
            last_seen = self.mod_message_cooldowns.get(message.author.id)
            if last_seen and (now - last_seen).total_seconds() < MOD_MESSAGE_COOLDOWN_SECONDS:
                return
            self.mod_message_cooldowns[message.author.id] = now
            self._increment_log(message.author.id, "mod_message_count")

    @app_commands.command(name="register", description="Register yourself in the staff logger")
    async def register(self, interaction: discord.Interaction):
        role_types = self._resolve_role_types(interaction.user)
        if not role_types:
            await interaction.response.send_message(
                "You do not have a trackable staff role.",
                ephemeral=True,
            )
            return

        self._upsert_staff_user(interaction.user.id, role_types)
        row = self._registered_row(interaction.user.id)
        if row and not row[4]:
            self._set_profile_field(interaction.user.id, "registered_at", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        embed = discord.Embed(title="Staff Registration", color=discord.Color.green())
        embed.add_field(name="Role Types", value=", ".join(role.upper() for role in role_types), inline=True)
        embed.add_field(name="Week", value=self._config_get("active_week_id", self._current_week_id()), inline=True)
        await interaction.response.send_message(embed=embed)

    def _build_progress_embed(self, member: discord.Member) -> discord.Embed | None:
        row = self._sync_member_registration(member)
        if not row:
            return None

        role_types = self._parse_role_types(row[0])
        is_on_break = row[1]
        logs = self._get_weekly_log(member.id)
        embed = discord.Embed(
            title="Weekly Progress",
            description=f"Tracking week: **{self._week_label(self._config_get('active_week_id', self._current_week_id()))}**",
            color=discord.Color.blurple(),
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)

        if "gman" in role_types:
            current = self._count_for(logs, "gman")
            embed.add_field(
                name=f"{GIVEAWAY_EMOJI} Giveaway Managers",
                value=f"{self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))} ({current}/{PING_REQUIREMENT})",
                inline=False,
            )
        if "eman" in role_types:
            current = self._count_for(logs, "eman")
            embed.add_field(
                name=f"{EVENT_EMOJI} Event Managers",
                value=f"{self._progress_bar(current, PING_REQUIREMENT, is_on_break=bool(is_on_break))} ({current}/{PING_REQUIREMENT})",
                inline=False,
            )
        if set(role_types) & {"mod", "tmod"}:
            current = self._count_for(logs, "mod")
            mod_role_type = "tmod" if "tmod" in role_types and "mod" not in role_types else "mod"
            mod_requirement = self._requirement_for(mod_role_type)
            label = "Trial Moderators" if mod_role_type == "tmod" else "Moderators"
            embed.add_field(
                name=f"{MOD_EMOJI} {label}",
                value=f"{self._progress_bar(current, mod_requirement, is_on_break=bool(is_on_break))} ({current}/{mod_requirement})",
                inline=False,
            )

        if is_on_break:
            embed.add_field(name="Status", value="🟦 On break", inline=False)
        return embed

    @app_commands.command(name="weeklyprogress", description="Show weekly staff progress")
    async def weekly_progress_slash(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ):
        if not self._can_use_staff_commands(interaction.user):
            await interaction.response.send_message(self._not_registered_message(), ephemeral=True)
            return
        target = user or interaction.user
        embed = self._build_progress_embed(target)
        if embed is None:
            await interaction.response.send_message("That user is not registered in the staff logger.", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="weeklyprogress", aliases=["wp"])
    async def weekly_progress_prefix(self, ctx: commands.Context, user: discord.Member | None = None):
        if not self._can_use_staff_commands(ctx.author):
            await ctx.send(self._not_registered_message())
            return
        target = user or ctx.author
        embed = self._build_progress_embed(target)
        if embed is None:
            await ctx.send("That user is not registered in the staff logger.")
            return
        await ctx.send(embed=embed)

    @app_commands.command(name="profile", description="Show your staff profile")
    async def profile_slash(self, interaction: discord.Interaction, user: discord.Member | None = None):
        if not self._can_use_staff_commands(interaction.user):
            await interaction.response.send_message(self._not_registered_message(), ephemeral=True)
            return
        target = user or interaction.user
        embed = self._build_profile_embed(target)
        if embed is None:
            await interaction.response.send_message("That user is not registered in the staff logger.", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="profile")
    async def profile_prefix(self, ctx: commands.Context, user: discord.Member | None = None):
        if not self._can_use_staff_commands(ctx.author):
            await ctx.send(self._not_registered_message())
            return
        target = user or ctx.author
        embed = self._build_profile_embed(target)
        if embed is None:
            await ctx.send("That user is not registered in the staff logger.")
            return
        await ctx.send(embed=embed)

    @app_commands.command(name="enterbday", description="Set your birthday for your staff profile")
    async def enter_bday_slash(
        self,
        interaction: discord.Interaction,
        day: app_commands.Range[int, 1, 31],
        month: app_commands.Range[int, 1, 12],
        year: app_commands.Range[int, 1900, 2100],
    ):
        if not self._is_registered(interaction.user.id):
            await interaction.response.send_message(self._not_registered_message(), ephemeral=True)
            return
        try:
            birthday = datetime(year, month, day)
        except ValueError:
            await interaction.response.send_message("That birthday is not a valid date.", ephemeral=True)
            return
        self._set_profile_field(interaction.user.id, "birthday", birthday.strftime("%Y-%m-%d"))
        await interaction.response.send_message("Birthday saved to your staff profile.", ephemeral=True)

    @commands.command(name="enterbday")
    async def enter_bday_prefix(self, ctx: commands.Context, day: int, month: int, year: int):
        if not self._is_registered(ctx.author.id):
            await ctx.send(self._not_registered_message())
            return
        try:
            birthday = datetime(year, month, day)
        except ValueError:
            await ctx.send("That birthday is not a valid date.")
            return
        self._set_profile_field(ctx.author.id, "birthday", birthday.strftime("%Y-%m-%d"))
        await ctx.send("Birthday saved to your staff profile.")

    @app_commands.command(name="staffprogress", description="Show all registered staff progress")
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_progress_slash(self, interaction: discord.Interaction):
        embed = await self._build_staff_overview_embed_filtered(interaction.guild, "mod")
        view = StaffProgressView(self, interaction.guild, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @commands.command(name="staffprogress")
    @commands.has_permissions(administrator=True)
    async def staff_progress_prefix(self, ctx: commands.Context):
        embed = await self._build_staff_overview_embed_filtered(ctx.guild, "mod")
        view = StaffProgressView(self, ctx.guild, ctx.author.id)
        await ctx.send(embed=embed, view=view)

    @app_commands.command(name="sotm", description="Award the SOTM role to up to 3 users")
    @app_commands.checks.has_permissions(administrator=True)
    async def sotm_slash(
        self,
        interaction: discord.Interaction,
        user1: discord.Member,
        user2: discord.Member | None = None,
        user3: discord.Member | None = None,
    ):
        sotm_role = interaction.guild.get_role(SOTM_ROLE_ID)
        if sotm_role is None:
            await interaction.response.send_message("SOTM role not found.", ephemeral=True)
            return

        targets = []
        for member in (user1, user2, user3):
            if member and member.id not in {target.id for target in targets}:
                targets.append(member)

        for member in targets:
            if sotm_role not in member.roles:
                await member.add_roles(sotm_role, reason="SOTM awarded")
            if self._is_registered(member.id):
                self._increment_total_stat(member.id, "sotm_count")

        embed = discord.Embed(title="SOTM Awarded", color=discord.Color.gold())
        embed.add_field(name="Recipients", value="\n".join(member.mention for member in targets), inline=False)
        embed.add_field(name="Role", value=sotm_role.mention, inline=True)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="sotm")
    @commands.has_permissions(administrator=True)
    async def sotm_prefix(
        self,
        ctx: commands.Context,
        user1: discord.Member,
        user2: discord.Member | None = None,
        user3: discord.Member | None = None,
    ):
        sotm_role = ctx.guild.get_role(SOTM_ROLE_ID)
        if sotm_role is None:
            await ctx.send("SOTM role not found.")
            return

        targets = []
        for member in (user1, user2, user3):
            if member and member.id not in {target.id for target in targets}:
                targets.append(member)

        for member in targets:
            if sotm_role not in member.roles:
                await member.add_roles(sotm_role, reason="SOTM awarded")
            if self._is_registered(member.id):
                self._increment_total_stat(member.id, "sotm_count")

        embed = discord.Embed(title="SOTM Awarded", color=discord.Color.gold())
        embed.add_field(name="Recipients", value="\n".join(member.mention for member in targets), inline=False)
        embed.add_field(name="Role", value=sotm_role.mention, inline=True)
        await ctx.send(embed=embed)

    @staff_group.command(name="break", description="Put a staff member on break")
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_break(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        days: app_commands.Range[int, 1, 365] | None = None,
    ):
        role_types = self._resolve_role_types(user)
        row = self._registered_row(user.id)
        stored_roles = role_types or (self._parse_role_types(row[0]) if row else [])
        if not stored_roles:
            await interaction.response.send_message("That user has no trackable staff role.", ephemeral=True)
            return

        removed_roles = [role for role in user.roles if role.id in STAFF_ROLE_IDS and role.id != TOUCHING_GRASS_ROLE_ID]
        break_role = interaction.guild.get_role(TOUCHING_GRASS_ROLE_ID)
        if break_role is None:
            await interaction.response.send_message("Touching Grass role not found.", ephemeral=True)
            return

        if removed_roles:
            await user.remove_roles(*removed_roles, reason="Staff break enabled")
        if break_role not in user.roles:
            await user.add_roles(break_role, reason="Staff break enabled")

        saved_roles = ",".join(str(role.id) for role in removed_roles)
        break_until = None
        if days is not None:
            break_until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        self.cursor.execute(
            """
            INSERT INTO staff_users (user_id, role_type, is_on_break, saved_roles, break_until)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                role_type = excluded.role_type,
                is_on_break = 1,
                saved_roles = excluded.saved_roles,
                break_until = excluded.break_until
            """,
            (user.id, self._serialize_role_types(stored_roles), saved_roles, break_until),
        )
        self.conn.commit()

        embed = discord.Embed(title="Staff Break Enabled", color=discord.Color.orange())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Stored Roles", value=", ".join(role.upper() for role in stored_roles), inline=True)
        embed.add_field(name="Break Role", value=break_role.mention, inline=True)
        embed.add_field(
            name="Duration",
            value=(
                f"{days} day(s)\nEnds: <t:{int(self._parse_break_until(break_until).timestamp())}:R>"
                if break_until is not None
                else "Permanent until changed manually"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @staff_group.command(name="endbreak", description="Restore a staff member from break")
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_end_break(self, interaction: discord.Interaction, user: discord.Member):
        row = self._registered_row(user.id)
        if not row or not row[1]:
            await interaction.response.send_message("That user is not currently on break.", ephemeral=True)
            return

        restored = await self._restore_member_roles(
            user,
            row[2],
            reason="Staff break ended manually",
        )
        self.cursor.execute(
            """
            UPDATE staff_users
            SET is_on_break = 0, saved_roles = NULL, break_until = NULL
            WHERE user_id = ?
            """,
            (user.id,),
        )
        self.conn.commit()

        embed = discord.Embed(title="Staff Break Ended", color=discord.Color.green())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Roles Restored", value="Yes" if restored else "No saved roles to restore", inline=True)
        await interaction.response.send_message(embed=embed)

    @staff_group.command(name="sethiredate", description="Manually set a user's hired date")
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_set_hire_date(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        day: app_commands.Range[int, 1, 31],
        month: app_commands.Range[int, 1, 12],
        year: app_commands.Range[int, 1900, 2100],
    ):
        if not self._is_registered(user.id):
            await interaction.response.send_message("That user is not registered in the staff logger.", ephemeral=True)
            return
        try:
            hired_date = datetime(year, month, day)
        except ValueError:
            await interaction.response.send_message("That hired date is not a valid date.", ephemeral=True)
            return
        self._set_profile_field(user.id, "hired_date", hired_date.strftime("%Y-%m-%d"))
        await interaction.response.send_message(
            f"Hired date updated for {user.mention} to {hired_date.strftime('%d %b %Y')}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffLoggerCog(bot))

