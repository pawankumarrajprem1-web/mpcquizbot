import telebot
from settings import get_user_settings, toggle_user_setting, generate_settings_keyboard

TOKEN = "YOUR_TELEBOT_TOKEN_HERE"
bot = telebot.TeleBot(TOKEN)

# /setting कमांड हैंडलर
@bot.message_handler(commands=['setting', 'settings'])
def setting_command(message):
    user_id = message.from_user.id
    
    welcome_text = (
        "⚙️ *ADVANCE QUIZ SETTINGS PANEL*\n\n"
        "✨ _यहाँ से आप अपने क्विज़ के सभी 12 एडवांस फीचर्स को कंट्रोल कर सकते हैं।_\n"
        "📌 *नोट:* ग्रुप और पर्सनल दोनों के लिए यही सेटिंग्स डायरेक्ट अप्लाई होंगी!\n\n"
        "👇 नीचे दिए गए बटन्स से ऑन/ऑफ करें:"
    )
    
    bot.send_message(
        message.chat.id, 
        welcome_text, 
        parse_mode="Markdown", 
        reply_markup=generate_settings_keyboard(user_id)
    )

# कॉलबैक हैंडलर (जब यूजर बटन्स पर क्लिक करेगा)
@bot.callback_query_handler(func=lambda call: call.data.startswith('set_') or call.data == 'start_quiz_final')
def handle_settings_callback(call):
    user_id = call.from_user.id
    
    if call.data == 'start_quiz_final':
        bot.answer_callback_query(call.id, "🎉 Settings saved successfully! Ready for Quiz.")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ *Settings Locked & Saved!* अब आप अपनी क्विज़ आईडी से लिंक करके धमाकेदार क्विज़ शुरू कर सकते हैं। 🚀",
            parse_mode="Markdown"
        )
        return

    # की को निकालें (जैसे set_neg_mark से neg_mark निकालना)
    action_key = call.data.replace('set_', '')
    
    # मैपिंग ठीक करने के लिए
    key_mapping = {
        "neg_mark": "negative_marking",
        "paid_quiz": "paid_quiz",
        "expl": "explanation",
        "pdf_gen": "pdf_gen",
        "html_gen": "html_gen",
        "anti_cheat": "anti_cheating",
        "q_shuffle": "question_shuffling",
        "opt_rand": "option_randomization",
        "no_repeat": "no_repeat_filter",
        "timer_q": "timer_per_q",
        "leaderboard": "leaderboard",
        "quiz_mode": "quiz_mode_type"
    }
    
    actual_key = key_mapping.get(action_key, action_key)
    
    # स्टेटस बदलें
    toggle_user_setting(user_id, actual_key)
    
    # कीबोर्ड को लाइव अपडेट करें ताकि तुरंत ऑन/ऑफ दिखे
    try:
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=generate_settings_keyboard(user_id)
        )
        bot.answer_callback_query(call.id, "⚙️ Setting Updated!")
    except Exception as e:
        pass

# /edit कमांड (खास क्विज़ में बदलाव के लिए)
@bot.message_handler(commands=['edit'])
def edit_command(message):
    bot.reply_to(message, "🛠️ `/edit` कमांड एक्टिव है। इसका उपयोग करके आप किसी विशेष क्विज़ के प्रश्नों या फॉर्मेट में बदलाव कर सकते हैं।", parse_mode="Markdown")

if __name__ == "__main__":
    print("🤖 Advanced Quiz Bot with Separate settings.py is running smoothly...")
    bot.infinity_polling()
