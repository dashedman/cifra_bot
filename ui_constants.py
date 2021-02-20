NO_CONFIG_MESSAGE = """
  Please create config.ini:
-------------------------------------------------------------------------------
  [data-base]
  host=localhost
  port=
  login=sqllogin
  password=sqlpassword
  name=my_db

  [streamlink]
  streamers = streamers.json
  plugins = streamlink_plugins/

  [telegram]
  token = 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
  dashboard = -1

  [logging]
  #logging levels:

  # CRITICAL    50
  # ERROR       40
  # WARNING     30
  # INFO        20 DEFFAULT
  # DEBUG       10
  # NOTSET      0
  level=20
"""

YES = "🟢"
NO = "🔴"
BACK = "⬆️ Back"
PREV = "⬅️"
NEXT = "➡️"
STOP = "⛔️"
REFRESH = "🔄"

ADDED = "Succsesful added!"
DELETED = "Succsesful deleted!"
SENDED = "Succsesful sended!"

ERROR = "Get some error("
FORWARD_ERROR = "Ошибка\nУбедитесь имеет ли бот доступ к отвечаемому сообщению.\nТак же вы можете связатся с нами другими способами, подробнее в описании."
WRONG = "Wrong command("
NOT_FOUND = "Not founded("
NOTHING_NEW = "Nothing is new."
WAIT = "Please wait..."
FINDED = "Finded!"
FIND_NO_ARGS = "Please write '/find some text' to seek streams.\nMinimal length of text 3!\nMaximal length of text 30!"
TO_SMALL = "Message is to small"

START_CMD = "Pick the streamer!"
HELP_CMD = """
/start - to get keyboard with streams
/help - to get list of commands
/notifications - to set notifications about stream
/find some text - to seek streams by text
/review some text - to send message to developers. Also, you can reply this command to media files for send media to devs.
"""
VIPHELP_CMD = """
/vipinfo - get raw info about msg
/viphelp - get help for admin commands

/add streamer data [, part] - add stream in reply to `streamer`, with `data` in dd.mm.yyyy, `part` of stream optional
/addv priority - add Dwag's video, with integer `priority` order
/addv2 priority - add Alison's video, with integer `priority` order

/del caption - delete one stream by `caption`
/delv caption - delete one Dwag's video by `caption`
/delv2 caption - delete one Alison's video by `caption`

/rep chat_id text - send `text` to the chat with `chat_id`, from bot face
/broadcast text - send `text` to the all chat that have one or more streamer notifications, from bot face
"""
NOTIFICATIONS_CMD = "Set the notifications"
UNKNOW_CMD = "Unknow command =/\nEnter /help to get list of commands"

PICK_MSG = [
    START_CMD,
    "Pick the year!",
    "Pick the month!",
    "Pick the stream!"
]

LATESTS = "Latests..."
VIDEOS = "Видео с ютуба - Dawg"
VIDEOS2 = "Видео с ютуба - Alison"

BOTTOM_KEYBOARD = "/start"

def build_stream_text(streamer):
    return f"👁 Стример {streamer['name']} запустил свою трансляцию, ссылка: https://{streamer['platform']}/{streamer['id']}"
