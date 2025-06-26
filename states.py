from aiogram.fsm.state import StatesGroup, State

class ChatStates(StatesGroup):
    waiting_for_chat_input = State()
    waiting_for_chat_delete = State()
