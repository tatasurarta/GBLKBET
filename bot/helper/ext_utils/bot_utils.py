import logging
import re
import threading
import time
import math
import psutil
import shutil

from bot.helper.telegram_helper.bot_commands import BotCommands
from bot import dispatcher, download_dict, download_dict_lock, STATUS_LIMIT, botStartTime
from telegram import InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from bot.helper.telegram_helper import button_build, message_utils

LOGGER = logging.getLogger(__name__)

MAGNET_REGEX = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"

URL_REGEX = r"(?:(?:https?|ftp):\/\/)?[\w/\-?=%.]+\.[\w/\-?=%.]+"

COUNT = 0
PAGE_NO = 1


class MirrorStatus:
    STATUS_UPLOADING = "𝐒𝐞𝐝𝐚𝐧𝐠 𝐃𝐢 𝐔𝐩𝐥𝐨𝐚𝐝, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...📤"
    STATUS_DOWNLOADING = "𝐒𝐞𝐝𝐚𝐧𝐠 𝐃𝐢 𝐔𝐧𝐝𝐮𝐡, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...📥"
    STATUS_CLONING = "𝐒𝐞𝐝𝐚𝐧𝐠 𝐃𝐢 𝐂𝐥𝐨𝐧𝐞, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...♻️"
    STATUS_WAITING = "𝐌𝐚𝐬𝐢𝐡 𝐀𝐧𝐭𝐫𝐢, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...📝"
    STATUS_FAILED = "𝐅𝐢𝐥𝐞𝐦𝐮 𝐆𝐚𝐠𝐚𝐥. 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬 🚫. 𝐌𝐞𝐧𝐠𝐡𝐚𝐩𝐮𝐬 𝐅𝐢𝐥𝐞..."
    STATUS_PAUSE = "𝐃𝐢𝐣𝐞𝐝𝐚...⭕"
    STATUS_ARCHIVING = "𝐒𝐞𝐝𝐚𝐧𝐠 𝐃𝐢 𝐀𝐫𝐬𝐢𝐩𝐤𝐚𝐧, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...🔐"
    STATUS_EXTRACTING = "𝐒𝐞𝐝𝐚𝐧𝐠 𝐃𝐢 𝐄𝐤𝐬𝐭𝐫𝐚𝐤, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...📂"
    STATUS_SPLITTING = "𝐒𝐞𝐝𝐚𝐧𝐠 𝐃𝐢 𝐏𝐢𝐬𝐚𝐡, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...✂️"
    STATUS_CHECKING = "𝐒𝐞𝐝𝐚𝐧𝐠 𝐃𝐢 𝐜𝐞𝐤, 𝐘𝐚𝐧𝐠 𝐒𝐀𝐁𝐀𝐑 𝐘𝐚 𝐁𝐨𝐬...📝"

SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']


class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = threading.Event()
        thread = threading.Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time.time() + self.interval
        while not self.stopEvent.wait(nextTime - time.time()):
            nextTime += self.interval
            self.action()

    def cancel(self):
        self.stopEvent.set()

def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File too large'

def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in download_dict.values():
            status = dl.status()
            if (
                status
                not in [
                    MirrorStatus.STATUS_ARCHIVING,
                    MirrorStatus.STATUS_EXTRACTING,
                    MirrorStatus.STATUS_SPLITTING,
                ]
                and dl.gid() == gid
            ):
                return dl
    return None

def getAllDownload():
    with download_dict_lock:
        for dlDetails in download_dict.values():
            status = dlDetails.status()
            if (
                status
                not in [
                    MirrorStatus.STATUS_ARCHIVING,
                    MirrorStatus.STATUS_EXTRACTING,
                    MirrorStatus.STATUS_SPLITTING,
                    MirrorStatus.STATUS_CLONING,
                    MirrorStatus.STATUS_UPLOADING,
                ]
                and dlDetails
            ):
                return dlDetails
    return None

def get_progress_bar_string(status):
    completed = status.processed_bytes() / 8
    total = status.size_raw() / 8
    p = 0 if total == 0 else round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 8
    p_str = '■' * cFull
    p_str += '□' * (12 - cFull)
    p_str = f"[{p_str}]"
    return p_str

def get_readable_message():
    with download_dict_lock:
        msg = ""
        START = 0
        dlspeed_bytes = 0
        uldl_bytes = 0
        if STATUS_LIMIT is not None:
            dick_no = len(download_dict)
            global pages
            pages = math.ceil(dick_no/STATUS_LIMIT)
            if pages != 0 and PAGE_NO > pages:
                globals()['COUNT'] -= STATUS_LIMIT
                globals()['PAGE_NO'] -= 1
            START = COUNT
        for index, download in enumerate(list(download_dict.values())[START:], start=1):
            msg += f"<b>📁 𝐍𝐚𝐦𝐚 𝐅𝐢𝐥𝐞:</b> <code>{download.name()}</code>"
            msg += f"\n<b>⏰ 𝐒𝐭𝐚𝐭𝐮𝐬:</b> <i>{download.status()}</i>"
            if download.status() not in [
                MirrorStatus.STATUS_ARCHIVING,
                MirrorStatus.STATUS_EXTRACTING,
                MirrorStatus.STATUS_SPLITTING,
            ]:
                msg += f"\n{get_progress_bar_string(download)} {download.progress()}"
                if download.status() == MirrorStatus.STATUS_CLONING:
                    msg += f"\n<b>♻️ 𝐊𝐥𝐨𝐧𝐢𝐧𝐠:</b> {get_readable_file_size(download.processed_bytes())}<b>\n<b>⚙️ 𝐌𝐞𝐬𝐢𝐧: ʀᴄʟᴏɴᴇ</b>\n💾 𝐔𝐤𝐮𝐫𝐚𝐧</b>: {download.size()}"
                elif download.status() == MirrorStatus.STATUS_UPLOADING:
                    msg += f"\n<b>📤 𝐌𝐄𝐍𝐆𝐔𝐍𝐆𝐆𝐀𝐇:</b> {get_readable_file_size(download.processed_bytes())}<b>\n<b>⚙️ 𝐌𝐞𝐬𝐢𝐧: ʀᴄʟᴏɴᴇ</b>\n💾 𝐔𝐤𝐮𝐫𝐚𝐧</b>: {download.size()}"
                else:
                    msg += f"\n<b>📥 𝐌𝐄𝐍𝐆𝐔𝐍𝐃𝐔𝐇:</b> {get_readable_file_size(download.processed_bytes())}<b>\n<b>⚙️ 𝐌𝐞𝐬𝐢𝐧: ʀᴄʟᴏɴᴇ</b>\n💾 𝐔𝐤𝐮𝐫𝐚𝐧</b>: {download.size()}"
                msg += f"\n<b>⚡ 𝐊𝐞𝐜𝐞𝐩𝐚𝐭𝐚𝐧 :</b> {download.speed()} <b>⏲️ 𝐄𝐬𝐭𝐢𝐦𝐚𝐬𝐢 :</b> {download.eta()}" \
                # if hasattr(download, 'is_torrent'):
                try:
                    msg += f"\n<b>👥 𝐏𝐞𝐧𝐠𝐠𝐮𝐧𝐚 :</b> <a href='tg://user?id={download.message.from_user.id}'>{download.message.from_user.first_name}</a>" \
                           f" | <b>⚠️ 𝐏𝐞𝐫𝐢𝐧𝐠𝐚𝐭𝐚𝐧:</b> <code>/warn {download.message.from_user.id}</code>"
                except:
                    pass
                try:
                    msg += f"\n<b>⚙️ ᴇɴɢɪɴᴇ : Aria2</b>\n<b>📶:</b> {download.aria_download().connections}"
                except:
                    pass
                try:
                    msg += f"\n<b>🌱 𝐒𝐞𝐞𝐝𝐞𝐫𝐬 :</b> {download.aria_download().num_seeders}" \
                           f" | <b>❇️ 𝐏𝐞𝐞𝐫𝐬 :</b> {download.aria_download().connections}"
                except:
                    pass
                try:
                    msg += f"\n<b>🌱 𝐒𝐞𝐞𝐝𝐞𝐫𝐬 :</b> {download.torrent_info().num_seeds}" \
                           f" | <b>🧲 𝐋𝐞𝐞𝐜𝐡𝐞𝐫𝐬 :</b> {download.torrent_info().num_leechs}"
                except:
                    pass    
                try:
                    msg += f"\n<b>⚙️ ᴇɴɢɪɴᴇ : Qbit</b>\n<b>🌍:</b> {download.torrent_info().num_leechs}"
                except:
                    pass
                msg += f"\n<b>⛔ 𝐔𝐧𝐭𝐮𝐤 𝐦𝐞𝐦𝐛𝐚𝐭𝐚𝐥𝐤𝐚𝐧 :</b> <code>/{BotCommands.CancelMirror} {download.gid()}</code>"
            msg += "\n\n"
            if STATUS_LIMIT is not None and index == STATUS_LIMIT:
                break
        if STATUS_LIMIT is not None and dick_no > STATUS_LIMIT:
            msg += f"<b>📑 𝐇𝐚𝐥𝐚𝐦𝐚𝐧:</b> {PAGE_NO}/{pages} | <b>📝 𝐓𝐮𝐠𝐚𝐬:</b> {dick_no}\n"
            buttons = button_build.ButtonMaker()
            buttons.sbutton("👈", "pre")
            buttons.sbutton("👉", "nex")
            button = InlineKeyboardMarkup(buttons.build_menu(2))
            return msg, button
        return msg, ""

def turn(update, context):
    query = update.callback_query
    query.answer()
    global COUNT, PAGE_NO
    if query.data == "nex":
        if PAGE_NO == pages:
            COUNT = 0
            PAGE_NO = 1
        else:
            COUNT += STATUS_LIMIT
            PAGE_NO += 1
    elif query.data == "pre":
        if PAGE_NO == 1:
            COUNT = STATUS_LIMIT * (pages - 1)
            PAGE_NO = pages
        else:
            COUNT -= STATUS_LIMIT
            PAGE_NO -= 1
    message_utils.update_all_messages()

def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result

def is_url(url: str):
    url = re.findall(URL_REGEX, url)
    return bool(url)

def is_gdrive_link(url: str):
    return "drive.google.com" in url

def is_gdtot_link(url: str):
    url = re.match(r'https?://.*\.gdtot\.\S+', url)
    return bool(url)

def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url

def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"

def is_magnet(url: str):
    magnet = re.findall(MAGNET_REGEX, url)
    return bool(magnet)

def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper


next_handler = CallbackQueryHandler(turn, pattern="nex", run_async=True)
previous_handler = CallbackQueryHandler(turn, pattern="pre", run_async=True)
dispatcher.add_handler(next_handler)
dispatcher.add_handler(previous_handler)
