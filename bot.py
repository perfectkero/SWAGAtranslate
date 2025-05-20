import logging
import os
from dotenv import load_dotenv

from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from typing import Optional, List

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

gemini_client: Optional[genai.Client] = None
SELECTED_GEMINI_MODEL = "gemini-2.0-flash" # Лучше использовать тот-же 2.0-flash, для скорости ответов

ACTIVE_MODES = {
    "slang_to_standard_russian": {
        "button_text": "Сленг 🧢 → Понятно 🧐",
        "gemini_prompt": "Твоя задача — объяснить этот текст, написанный на современном русскоязычном молодежном сленге, простым, ясным и общепонятным литературным русским языком. Главное — сделать смысл доступным для человека, не знакомого со сленгом. Сохрани исходную мысль и эмоциональный окрас. Текст должен звучать естественно и грамотно."
    },
    "standard_russian_to_slang": {
        "button_text": "Понятно 🧐 → Сленг 🧢",
        "gemini_prompt": "Твоя задача — перевести этот текст, написанный на стандартном русском языке, на современный молодежный сленг (для аудитории 16-25 лет). Сделай текст максимально неформальным, живым, добавь характерные словечки и обороты. Важно точно передать смысл в сленговой манере."
    }
}


async def translate_text_with_gemini(text_to_translate: str, mode_key: str) -> str | None:
    if not gemini_client:
        logger.critical("Клиент Gemini не инициализирован при попытке перевода.")
        return None
    mode_info = ACTIVE_MODES.get(mode_key)
    if not mode_info:
        logger.error(f"Попытка использовать несуществующий режим: {mode_key}")
        return None

    specific_task_description = mode_info["gemini_prompt"]

    prompt = f"""Ты — ИИ-помощник, специализирующийся на переводе между современным русским молодежным сленгом и общепонятным литературным русским языком.
{specific_task_description}

Важно:
- Сохраняй основной смысл исходного текста.
- Адаптируй лексику, грамматику и тональность под целевой стиль.
- Выдавай **только** переведенный текст, без каких-либо своих вступлений, извинений, объяснений твоего процесса или комментариев.

Исходный текст для перевода:
"{text_to_translate}"

Результат (только переведенный текст):"""

    try:
        response = await gemini_client.aio.models.generate_content(
            model=SELECTED_GEMINI_MODEL,
            contents=prompt
        )
        if response and response.text:
            return response.text.strip()
        else:
            logger.error(f"Gemini не вернул текст. Feedback: {getattr(response, 'prompt_feedback', 'N/A')}")
            return None
    except Exception as e:
        logger.error(f"Критическая ошибка при запросе к Gemini API: {e}", exc_info=True)
        return None


def build_translation_mode_keyboard() -> InlineKeyboardMarkup:
    keyboard_row: List[InlineKeyboardButton] = [
        InlineKeyboardButton(details["button_text"], callback_data=f"mode_{key}")
        for key, details in ACTIVE_MODES.items()
    ]
    return InlineKeyboardMarkup([keyboard_row])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        user = update.effective_user
        await update.message.reply_html(
            f"Привет, {user.mention_html()}!\n\n"
            f"Отправь мне текст, и я помогу перевести его со сленга на понятный язык или наоборот. 📝🔄"
        )
        context.user_data.clear()


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text: return

    context.user_data['original_text'] = update.message.text
    reply_markup = build_translation_mode_keyboard()
    await update.message.reply_text("Выберите направление перевода:", reply_markup=reply_markup)


async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.message: return
    await query.answer()

    mode_key = query.data[len("mode_"):]
    if mode_key not in ACTIVE_MODES:
        await query.edit_message_text("😕 Ошибка: выбран неизвестный режим.", reply_markup=None)
        return

    selected_mode_button_text = ACTIVE_MODES[mode_key]["button_text"]
    original_text = context.user_data.pop('original_text', None)

    if not original_text:
        await query.edit_message_text("😕 Ошибка: текст для перевода не найден. Пожалуйста, отправьте его снова.",
                                      reply_markup=None)
        return

    await query.edit_message_text(
        text=f"Перевожу: \"{selected_mode_button_text}\". Подождите... ⏳",
        reply_markup=None
    )

    translated_text = await translate_text_with_gemini(original_text, mode_key)

    if translated_text:
        result_message = f"🧐 *Результат*:\n\n{translated_text}\n\n➖➖➖➖➖\n" \
                         f"Отправьте новый текст, если нужно."
        await query.edit_message_text(text=result_message, parse_mode='Markdown', reply_markup=None)
    else:
        error_message = f"😕 Упс! Не удалось перевести в режиме «{selected_mode_button_text}»."
        await query.edit_message_text(text=error_message, reply_markup=None)


def main() -> None:
    global gemini_client
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN не найден! Запуск невозможен.")
        return
    if not GEMINI_API_KEY:
        logger.critical("GEMINI_API_KEY не найден! Запуск невозможен.")
        return

    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.critical(f"Критическая ошибка инициализации клиента Gemini: {e}", exc_info=True)
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^mode_"))

    print("Бот запущен и готов к работе.")
    application.run_polling()


if __name__ == "__main__":
    main()