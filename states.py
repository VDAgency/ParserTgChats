from aiogram.fsm.state import StatesGroup, State

class ChatStates(StatesGroup):
    waiting_for_chat_input = State()
    waiting_for_chat_delete = State()


class KeywordStates(StatesGroup):
    waiting_for_keywords_input = State()
    waiting_for_negative_keywords = State()
    waiting_for_keyword_deletion = State()
    waiting_for_negative_keyword_deletion = State()

class KeywordLemmaState(StatesGroup):
    keywords_lemma_intent = State()
    keywords_lemma_object = State()
    keywords_lemma_region = State()
    keywords_lemma_beach = State()
    keywords_lemma_bedrooms = State()
    keywords_lemma_intent_deletion = State()
    keywords_lemma_object_deletion = State()
    keywords_lemma_region_deletion = State()
    keywords_lemma_beach_deletion = State()
    keywords_lemma_bedrooms_deletion = State()

    