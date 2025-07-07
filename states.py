from aiogram.fsm.state import StatesGroup, State

class ChatStates(StatesGroup):
    waiting_for_chat_input = State()
    waiting_for_chat_delete = State()


class KeywordStates(StatesGroup):
    waiting_for_keywords_input = State()
    waiting_for_negative_keywords = State()
    waiting_for_keyword_deletion = State()

