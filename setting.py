"""
============================================================
🤖 ADVANCED TELEGRAM QUIZ BOT - COMPREHENSIVE FEATURE MODULE
------------------------------------------------------------
Author: Amar (Aryan)
Description: Complete 12-Feature Management System for Quiz Bot.
             Handles interactive 3x4 grid inline keyboards, real-time 
             toggle states (ON/OFF), back navigation, and data mapping.
============================================================
"""

import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# लॉगिंग सेटअप ताकि कोई भी एरर आसानी से ट्रैक हो सके
logger = logging.getLogger(__name__)

# ==========================================
# 1. DEFAULT CONFIGURATION FOR ALL 12 FEATURES
# ==========================================
DEFAULT_QUIZ_FEATURES = {
    "negative_marking": False,     # ❌ गलत जवाब पर नेगेटिव मार्किंग
    "paid_quiz": False,            # 💳 पेड क्विज़ / कॉइन वेरिफिकेशन
    "explanation": True,           # 💡 उत्तर के बाद विस्तृत व्याख्या
    "pdf_gen": False,              # 📄 क्विज़ खत्म होने पर PDF जनरेशन
    "html_gen": False,             # 🌐 वेब/HTML फॉर्मेट में एक्सपोर्ट
    "anti_cheating": False,        # 🛡️ एंटी-चीटिंग मोड (स्ट्रिक्ट चेकिंग)
    "question_shuffling": True,    # 🔀 प्रश्नों का क्रम रैंडम करना (Shuffling)
    "option_randomization": True,  # 🔠 ऑप्शंस (A, B, C, D) की पोजीशन बदलना
    "no_repeat_filter": True,      # 🔄 हाल ही में आए सवालों को दोबारा आने से रोकना
    "timer_per_q": False,          # ⏱️ प्रति प्रश्न टाइमर लिमिट
    "leaderboard": True,           # 🏆 लीडरबोर्ड स्कोर डिस्प्ले मोड
    "quiz_mode_type": True         # 🎯 True = Practice Mode, False = Test Mode
}

# मेमोरी डेटाबेस (यूजर्स की सेटिंग्स को स्टोर करने के लिए)
# आप चाहें तो इसे बाद में अपने मुख्य database.py से जोड़ सकते हैं
user_features_database = {}


def get_user_features(user_id: int) -> dict:
    """
    यूजर की वर्तमान सेटिंग्स प्राप्त करें। 
    यदि यूजर पहली बार आया है, तो डिफ़ॉल्ट सेटिंग्स असाйн कर दें।
    """
    if user_id not in user_features_database:
        # कॉपीड डिफ़ॉल्ट डिक्शनरी ताकि एक यूजर की सेटिंग दूसरे पर असर न डाले
        user_features_database[user_id] = DEFAULT_QUIZ_FEATURES.copy()
    return user_features_database[user_id]


def toggle_specific_feature(user_id: int, feature_key: str) -> dict:
    """
    किसी भी फीचर के स्टेट को ON से OFF या OFF से ON टॉगल करने का मुख्य फंक्शन।
    """
    features = get_user_features(user_id)
    if feature_key in features:
        # यदि यह प्रैक्टिस/टेस्ट मोड है, तो इसे भी हैंडल करेंगे
        features[feature_key] = not features[feature_key]
        logger.info(f"User {user_id} toggled {feature_key} to {features[feature_key]}")
    return features


def reset_user_features(user_id: int) -> dict:
    """
    सभी सेटिंग्स को वापस डिफ़ॉल्ट मोड में रीसेट करने के लिए।
    """
    user_features_database[user_id] = DEFAULT_QUIZ_FEATURES.copy()
    return user_features_database[user_id]


# ==========================================
# 2. ADVANCED 3x4 GRID INLINE KEYBOARD BUILDER
# ==========================================
def build_feature_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    12 एडवांस फीचर्स के लिए 3-3 बटन्स की 4 पंक्तियाँ (3x4 Grid) जनरेट करता है।
    साथ ही नीचे नेविगेशन और सेव/बैक के बटन्स जोड़ता है।
    """
    features = get_user_features(user_id)
    markup = InlineKeyboardMarkup(row_width=3)
    
    # 12 फीचर्स की पूरी लिस्ट (बटन का नाम, इंटरनल की, वर्तमान स्टेटस)
    feature_items = [
        ("❌ Neg Marking", "neg_mark", features["negative_marking"]),
        ("💳 Paid Quiz", "paid_quiz", features["paid_quiz"]),
        ("💡 Explanation", "expl", features["explanation"]),
        ("📄 PDF Gen", "pdf_gen", features["pdf_gen"]),
        ("🌐 HTML Gen", "html_gen", features["html_gen"]),
        ("🛡️ Anti-Cheat", "anti_cheat", features["anti_cheating"]),
        ("🔀 Q-Shuffle", "q_shuffle", features["question_shuffling"]),
        ("🔠 Opt Random", "opt_rand", features["option_randomization"]),
        ("🔄 No Repeat", "no_repeat", features["no_repeat_filter"]),
        ("⏱️ Timer/Q", "timer_q", features["timer_per_q"]),
        ("🏆 Leaderboard", "leaderboard", features["leaderboard"]),
        ("🎯 Quiz Mode", "quiz_mode", features["quiz_mode_type"])
    ]
    
    keyboard_buttons = []
    for label, key_name, status in feature_items:
        # स्टेट्स के आधार पर आइकन सेट करना
        if key_name == "quiz_mode":
            status_display = "🟢 Practice" if status else "🟠 Test"
        else:
            status_display = "✅ ON" if status else "❌ OFF"
            
        button_text = f"{label} : {status_display}"
        # कॉलबैक डेटा में 'feat_' प्रीफिक्स का इस्तेमाल ताकि यह कन्फ्यूज न हो
        keyboard_buttons.append(InlineKeyboardButton(button_text, callback_data=f"feat_toggle_{key_name}"))
    
    # 3-3 बटन्स करके कुल 4 रो (Rows) में अरेंज करना
    for i in range(0, len(keyboard_buttons), 3):
        row_slice = keyboard_buttons[i:i+3]
        markup.row(*row_slice)
        
    # नीचे अतिरिक्त कंट्रोल बटन्स (रीसेट, बैक, और फाइनल सेव)
    markup.row(
        InlineKeyboardButton("🔄 Reset Default", callback_data="feat_action_reset"),
        InlineKeyboardButton("🔙 Back", callback_data="feat_action_back")
    )
    markup.add(InlineKeyboardButton("🚀 Save & Start Quiz Directly", callback_data="feat_action_save"))
    
    return markup


# ==========================================
# 3. MAPPING SHORT KEYS TO ACTUAL DICTIONARY KEYS
# ==========================================
def resolve_feature_key(short_key: str) -> str:
    """
    कॉलबैक डेटा से मिलने वाली छोटी की को वास्तविक डिक्शनरी की से मिलाता है।
    """
    mapping = {
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
    return mapping.get(short_key, short_key)


# ==========================================
# 4. FINAL CONFIG EXPORTER FOR QUIZ ENGINE / STORAGE
# ==========================================
def get_final_quiz_execution_config(user_id: int) -> dict:
    """
    जब यूजर अपनी सेटिंग्स लॉक करके क्विज़ शुरू करेगा, 
    तब यह डेटाबेस या क्विज़ इंजन के लिए फाइनल कॉन्फ़िगरेशन रिटर्न करेगा।
    """
    features = get_user_features(user_id)
    return {
        "user_id": user_id,
        "negative_marking": features["negative_marking"],
        "paid_quiz": features["paid_quiz"],
        "explanation": features["explanation"],
        "pdf_gen": features["pdf_gen"],
        "html_gen": features["html_gen"],
        "anti_cheating": features["anti_cheating"],
        "question_shuffling": features["question_shuffling"],
        "option_randomization": features["option_randomization"],
        "no_repeat_filter": features["no_repeat_filter"],
        "timer_per_q": features["timer_per_q"],
        "leaderboard": features["leaderboard"],
        "quiz_mode_type": features["quiz_mode_type"], # True -> Practice, False -> Test
        "status": "LOCKED_AND_READY"
    }


# ==========================================
# 5. TELEGRAM HANDLERS (Integration for runner.py / main handler)
# ==========================================
def register_feature_handlers(bot):
    """
    इस फंक्शन को आप अपनी मेन फाइल या runner.py से कॉल कर सकते हैं 
    ताकि बॉट में `/feature` कमांड रजिस्टर हो जाए।
    """

    @bot.message_handler(commands=['feature', 'features'])
    def feature_command_handler(message):
        user_id = message.from_user.id
        
        welcome_message = (
            "⚙️ *ADVANCED QUIZ FEATURE MANAGER* ⚙️\n\n"
            "✨ _यहाँ से आप अपने एडवांस क्विज़ बॉट के सभी 12 मोड्स को कंट्रोल कर सकते हैं।_\n"
            "📌 *नोट:* ग्रुप और पर्सनल दोनों चैट के लिए यही सेटिंग्स डायरेक्ट अप्लाई होंगी!\n\n"
            "👇 अपनी पसंद के अनुसार किसी भी विकल्प पर क्लिक करके ON/OFF करें:"
        )
        
        try:
            bot.send_message(
                message.chat.id,
                welcome_message,
                parse_mode="Markdown",
                reply_markup=build_feature_settings_keyboard(user_id)
            )
        except Exception as e:
            logger.error(f"Error sending feature panel: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('feat_'))
    def feature_callback_router(call):
        user_id = call.from_user.id
        data = call.data
        
        try:
            if data.startswith('feat_toggle_'):
                # किसी फीचर को टॉगल करना (ON/OFF करना)
                short_key = data.replace('feat_toggle_', '')
                actual_key = resolve_feature_key(short_key)
                
                # स्टेट बदलें
                toggle_specific_feature(user_id, actual_key)
                
                # कीबोर्ड को लाइव अपडेट करें (बिना नया मैसेज भेजे)
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=build_feature_settings_keyboard(user_id)
                )
                bot.answer_callback_query(call.id, "⚡ Feature Status Updated Successfully!")

            elif data == 'feat_action_reset':
                # सभी सेटिंग्स डिफ़ॉल्ट करना
                reset_user_features(user_id)
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=build_feature_settings_keyboard(user_id)
                )
                bot.answer_callback_query(call.id, "🔄 All settings reset to default!")

            elif data == 'feat_action_back':
                # बैक जाने का एक्शन
                bot.answer_callback_query(call.id, "🔙 Main menu / Back action.")
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="❌ *Feature panel closed or went back.* \nआप दोबारा `/feature` टाइप करके इसे खोल सकते हैं।",
                    parse_mode="Markdown"
                )

            elif data == 'feat_action_save':
                # फाइनल सेव और क्विज़ लिंक करने का स्टेज
                final_config = get_final_quiz_execution_config(user_id)
                
                success_text = (
                    "🎉 *SETTINGS LOCKED & SAVED SUCCESSFULLY!* 🚀\n\n"
                    f"📌 *Active Mode Summary:*\n"
                    f"• Negative Marking : `{'ON' if final_config['negative_marking'] else 'OFF'}`\n"
                    f"• Paid Quiz Mode   : `{'ON' if final_config['paid_quiz'] else 'OFF'}`\n"
                    f"• Explanation      : `{'ON' if final_config['explanation'] else 'OFF'}`\n"
                    f"• Q-Shuffling      : `{'ON' if final_config['question_shuffling'] else 'OFF'}`\n"
                    f"• Anti-Cheating    : `{'ON' if final_config['anti_cheating'] else 'OFF'}`\n"
                    f"• Quiz Pattern     : `{'Practice Mode' if final_config['quiz_mode_type'] else 'Test Mode'}`\n\n"
                    "_अब आप अपनी क्विज़ आईडी या डेटा से सीधे सवाल जनरेट कर सकते हैं!_ ✨"
                )
                
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=success_text,
                    parse_mode="Markdown"
                )
                bot.answer_callback_query(call.id, "🚀 Settings saved and locked for your Quiz!")
                
                # ==========================================
                # TODO: यहाँ से आप अपने क्विज़ इंजन/डेटाबेस को कॉल कर सकते हैं 
                # और 'final_config' को पास कर सकते हैं।
                # ==========================================

        except Exception as e:
            logger.error(f"Error handling feature callback: {e}")
            bot.answer_callback_query(call.id, "⚠️ An error occurred, please try again.")
