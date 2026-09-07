"""
====================================================================
🤖 ADVANCED QUIZ BOT - ULTIMATE FEATURE & DASHBOARD MODULE (features.py)
--------------------------------------------------------------------
Author: Amar (Aryan)
Description: Complete 12-Feature Management System with Sub-Menus,
             Dynamic Negative Marking Customization, Anti-Cheating, 
             Timer Options, and Interactive Dashboard triggered by /editfeature.
====================================================================
"""

import os
import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# लॉगिंग कॉन्फ़िगरेशन
logger = logging.getLogger(__name__)

# ====================================================================
# 1. ADVANCED DEFAULT CONFIGURATION (ALL 12 MODES & SUB-SETTINGS)
# ====================================================================
DEFAULT_QUIZ_FEATURES = {
    # 1. Negative Marking (Options: OFF, 0.25, 0.33, 0.50, CUSTOM)
    "negative_marking_status": False,
    "negative_marking_value": 0.33,
    
    # 2. Paid Quiz Integration
    "paid_quiz": False,
    "paid_quiz_amount": "0 Coins",
    
    # 3. Detailed Explanation
    "explanation": True,
    
    # 4. PDF Generation
    "pdf_gen": False,
    
    # 5. HTML Generation
    "html_gen": False,
    
    # 6. Anti-Cheating Mode
    "anti_cheating": False,
    "anti_cheating_level": "Strict",
    
    # 7. Smart Question Shuffling
    "question_shuffling": True,
    
    # 8. Option Randomization
    "option_randomization": True,
    
    # 9. No Repeat Filter
    "no_repeat_filter": True,
    
    # 10. Timer Per Question (Options: OFF, 10s, 30s, 60s, CUSTOM)
    "timer_per_q": False,
    "timer_seconds": 30,
    
    # 11. Leaderboard Mode
    "leaderboard": True,
    
    # 12. Quiz Mode Type (True = Practice Mode, False = Test Mode)
    "quiz_mode_type": True,
    
    # State tracker to know if user is inside a sub-menu
    "current_menu": "MAIN_DASHBOARD"
}

# यूजर सेटिंग्स का डेटाबेस (मेモリ स्टोरेज)
user_features_database = {}
# यूजर के कस्टम इनपुट स्टेटस को ट्रैक करने के लिए (जैसे नेगेटिव मार्किंग वैल्यू टाइप करना)
user_pending_inputs = {}


def get_user_features(user_id: int) -> dict:
    """यूजर की सेटिंग्स प्राप्त करें या डिफ़ॉल्ट असाइन करें।"""
    if user_id not in user_features_database:
        user_features_database[user_id] = DEFAULT_QUIZ_FEATURES.copy()
    return user_features_database[user_id]


def reset_user_features(user_id: int) -> dict:
    """सभी सेटिंग्स को वापस डिफ़ॉल्ट में रीसेट करें।"""
    user_features_database[user_id] = DEFAULT_QUIZ_FEATURES.copy()
    return user_features_database[user_id]


# ====================================================================
# 2. MAIN 3x4 GRID DASHBOARD KEYBOARD GENERATOR
# ====================================================================
def build_main_dashboard_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    12 एडवांस फीचर्स के लिए मुख्य 3x4 ग्रिड इनलाइन कीबोर्ड जनरेटर।
    प्रत्येक बटन पर क्लिक करने पर या तो सीधा टॉगल होगा या उसका सब-मेनू खुलेगा।
    """
    features = get_user_features(user_id)
    features["current_menu"] = "MAIN_DASHBOARD"
    
    markup = InlineKeyboardMarkup(row_width=3)
    
    # 12 फीचर्स (नाम, कॉलबैक की, स्टेटस या वैल्यू डिस्प्ले)
    neg_display = f"ON ({features['negative_marking_value']})" if features["negative_marking_status"] else "OFF"
    timer_display = f"ON ({features['timer_seconds']}s)" if features["timer_per_q"] else "OFF"
    quiz_type_display = "Practice" if features["quiz_mode_type"] else "Test"
    
    feature_grid_items = [
        (f"❌ Neg Mark: {neg_display}", "sub_neg_menu"),
        (f"💳 Paid Quiz: {'ON' if features['paid_quiz'] else 'OFF'}", "feat_toggle_paid_quiz"),
        (f"💡 Expl: {'ON' if features['explanation'] else 'OFF'}", "feat_toggle_explanation"),
        (f"📄 PDF Gen: {'ON' if features['pdf_gen'] else 'OFF'}", "feat_toggle_pdf_gen"),
        (f"🌐 HTML Gen: {'ON' if features['html_gen'] else 'OFF'}", "feat_toggle_html_gen"),
        (f"🛡️ Anti-Cheat: {'ON' if features['anti_cheating'] else 'OFF'}", "sub_anti_cheat_menu"),
        (f"🔀 Q-Shuffle: {'ON' if features['question_shuffling'] else 'OFF'}", "feat_toggle_q_shuffle"),
        (f"🔠 Opt Rand: {'ON' if features['option_randomization'] else 'OFF'}", "feat_toggle_opt_rand"),
        (f"🔄 No Repeat: {'ON' if features['no_repeat_filter'] else 'OFF'}", "feat_toggle_no_repeat"),
        (f"⏱️ Timer: {timer_display}", "sub_timer_menu"),
        (f"🏆 Leaderboard: {'ON' if features['leaderboard'] else 'OFF'}", "feat_toggle_leaderboard"),
        (f"🎯 Mode: {quiz_type_display}", "feat_toggle_quiz_mode")
    ]
    
    keyboard_buttons = []
    for label, callback_data in feature_grid_items:
        keyboard_buttons.append(InlineKeyboardButton(label, callback_data=callback_data))
    
    # 3-3 बटन्स की 4 पंक्तियाँ बनाना (3x4 Grid)
    for i in range(0, len(keyboard_buttons), 3):
        row_slice = keyboard_buttons[i:i+3]
        markup.row(*row_slice)
        
    # नीचे कंट्रोल बटन्स (रीसेट और फाइनल सेव)
    markup.row(
        InlineKeyboardButton("🔄 Reset All", callback_data="feat_action_reset"),
        InlineKeyboardButton("❌ Close Panel", callback_data="feat_action_close")
    )
    markup.add(InlineKeyboardButton("🚀 Save Settings & Lock Quiz", callback_data="feat_action_save"))
    
    return markup


# ====================================================================
# 3. SUB-MENU KEYBOARDS (Negative Marking & Timer Customization)
# ====================================================================
def build_negative_marking_submenu(user_id: int) -> InlineKeyboardMarkup:
    """नेगेटिव मार्किंग के लिए एडवांस्ड सब-मेनू (अलग-अलग वैल्यूज़ और कस्टम इनपुट)।"""
    features = get_user_features(user_id)
    features["current_menu"] = "SUB_NEG_MARKING"
    
    markup = InlineKeyboardMarkup(row_width=2)
    status_icon = "🟢 ACTIVE" if features["negative_marking_status"] else "🔴 INACTIVE"
    
    markup.add(InlineKeyboardButton(f"Toggle Status: {status_icon}", callback_data="neg_sub_toggle"))
    markup.row(
        InlineKeyboardButton("0.25 Marks", callback_data="neg_val_0.25"),
        InlineKeyboardButton("0.33 Marks", callback_data="neg_val_0.33")
    )
    markup.row(
        InlineKeyboardButton("0.50 Marks", callback_data="neg_val_0.50"),
        InlineKeyboardButton("1.00 Mark", callback_data="neg_val_1.00")
    )
    markup.add(InlineKeyboardButton("✏️ Enter Custom Negative Value (Other)", callback_data="neg_val_custom"))
    markup.add(InlineKeyboardButton("🔙 Back to Main Dashboard", callback_data="feat_action_back_main"))
    
    return markup


def build_timer_submenu(user_id: int) -> InlineKeyboardMarkup:
    """प्रति प्रश्न टाइमर के लिए एडवांस्ड सब-मेनू।"""
    features = get_user_features(user_id)
    features["current_menu"] = "SUB_TIMER"
    
    markup = InlineKeyboardMarkup(row_width=2)
    status_icon = "🟢 ACTIVE" if features["timer_per_q"] else "🔴 INACTIVE"
    
    markup.add(InlineKeyboardButton(f"Toggle Timer: {status_icon}", callback_data="timer_sub_toggle"))
    markup.row(
        InlineKeyboardButton("10 Seconds", callback_data="timer_val_10"),
        InlineKeyboardButton("30 Seconds", callback_data="timer_val_30")
    )
    markup.row(
        InlineKeyboardButton("60 Seconds", callback_data="timer_val_60"),
        InlineKeyboardButton("90 Seconds", callback_data="timer_val_90")
    )
    markup.add(InlineKeyboardButton("🔙 Back to Main Dashboard", callback_data="feat_action_back_main"))
    
    return markup


# ====================================================================
# 4. FINAL QUIZ CONFIGURATION EXPORTER
# ====================================================================
def get_final_quiz_execution_config(user_id: int) -> dict:
    """क्रिएटर बॉट और क्विज़ इंजन के लिए फाइनल डेटा पैकेज।"""
    features = get_user_features(user_id)
    return {
        "user_id": user_id,
        "negative_marking_status": features["negative_marking_status"],
        "negative_marking_value": features["negative_marking_value"],
        "paid_quiz": features["paid_quiz"],
        "explanation": features["explanation"],
        "pdf_gen": features["pdf_gen"],
        "html_gen": features["html_gen"],
        "anti_cheating": features["anti_cheating"],
        "question_shuffling": features["question_shuffling"],
        "option_randomization": features["option_randomization"],
        "no_repeat_filter": features["no_repeat_filter"],
        "timer_per_q": features["timer_per_q"],
        "timer_seconds": features["timer_seconds"],
        "leaderboard": features["leaderboard"],
        "quiz_mode_type": features["quiz_mode_type"], # True = Practice, False = Test
        "status": "LOCKED_AND_READY"
    }


# ====================================================================
# 5. TELEGRAM HANDLERS REGISTRATION FOR CREATOR BOT (/editfeature)
# ====================================================================
def register_feature_handlers(bot):
    """इस फंक्शन को आपके क्रिएटर बॉट के मुख्य रनर में कॉल किया जाएगा।"""

    @bot.message_handler(commands=['editfeature', 'edit_feature', 'editfeatures'])
    def edit_feature_command_handler(message):
        user_id = message.from_user.id
        
        # यदि यूजर पहले से पेंडिंग इनपुट मोड में था, उसे रीसेट करें
        if user_id in user_pending_inputs:
            del user_pending_inputs[user_id]
            
        welcome_text = (
            "⚙️ *ADVANCED CREATOR BOT - EDIT FEATURE DASHBOARD* ⚙️\n\n"
            "✨ _यहाँ से आप अपने क्विज़ के सभी 12 एडवांस मोड्स को एडिट और कस्टमाइज़ कर सकते हैं।_\n"
            "📌 *नोट:* ग्रुप और पर्सनल दोनों चैट के लिए यही सेटिंग्स डायरेक्ट अप्लाई होंगी!\n\n"
            "👇 किसी भी विकल्प पर क्लिक करके उसकी सेटिंग्स बदलें:"
        )
        
        try:
            bot.send_message(
                message.chat.id,
                welcome_text,
                parse_mode="Markdown",
                reply_markup=build_main_dashboard_keyboard(user_id)
            )
        except Exception as e:
            logger.error(f"Error opening editfeature dashboard: {e}")

    # टेक्स्ट इनपुट हैंडलर (कस्टम नेगेटिव वैल्यू या अन्य इनपुट टाइप करने के लिए)
    @bot.message_handler(func=lambda msg: msg.from_user.id in user_pending_inputs)
    def handle_custom_user_input(message):
        user_id = message.from_user.id
        action_type = user_pending_inputs.get(user_id)
        
        try:
            if action_type == "WAITING_FOR_CUSTOM_NEG":
                val = float(message.text.strip())
                features = get_user_features(user_id)
                features["negative_marking_value"] = val
                features["negative_marking_status"] = True
                
                del user_pending_inputs[user_id]
                bot.reply_to(
                    message,
                    f"✅ *सफलतापूर्वक सेट हो गया!* नेगेटिव मार्किंग वैल्यू अब `{val}` हो गई है और यह चालू (ON) है।",
                    parse_mode="Markdown",
                    reply_markup=build_main_dashboard_keyboard(user_id)
                )
        except ValueError:
            bot.reply_to(message, "⚠️ अमान्य मान (Invalid value)! कृपया केवल संख्या (जैसे 0.25 या 0.5) टाइप करें:")

    # कॉलबैक क्वेरी राउटर
    @bot.callback_query_handler(func=lambda call: call.data.startswith(('feat_', 'sub_', 'neg_', 'timer_')))
    def feature_callback_router(call):
        user_id = call.from_user.id
        data = call.data
        features = get_user_features(user_id)
        
        try:
            # 1. मेन टॉगल फीचर्स
            if data == 'feat_toggle_paid_quiz':
                features["paid_quiz"] = not features["paid_quiz"]
            elif data == 'feat_toggle_explanation':
                features["explanation"] = not features["explanation"]
            elif data == 'feat_toggle_pdf_gen':
                features["pdf_gen"] = not features["pdf_gen"]
            elif data == 'feat_toggle_html_gen':
                features["html_gen"] = not features["html_gen"]
            elif data == 'feat_toggle_q_shuffle':
                features["question_shuffling"] = not features["question_shuffling"]
            elif data == 'feat_toggle_opt_rand':
                features["option_randomization"] = not features["option_randomization"]
            elif data == 'feat_toggle_no_repeat':
                features["no_repeat_filter"] = not features["no_repeat_filter"]
            elif data == 'feat_toggle_leaderboard':
                features["leaderboard"] = not features["leaderboard"]
            elif data == 'feat_toggle_quiz_mode':
                features["quiz_mode_type"] = not features["quiz_mode_type"] # Practice <-> Test
                
            # यदि मुख्य ग्रिड का कोई सिंपल टॉगल है, तो डैशबोर्ड अपडेट करें
            if data.startswith('feat_toggle_'):
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=build_main_dashboard_keyboard(user_id)
                )
                bot.answer_callback_query(call.id, "⚡ Feature Updated!")
                return

            # 2. सब-मेनू नेविगेशन (Negative Marking Sub-menu)
            if data == 'sub_neg_menu':
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="❌ *Negative Marking Configuration*\n\nअपनी पसंद का नेगेटिव मार्किंग प्रतिशत चुनें या 'Other' के जरिए कस्टम वैल्यू टाइप करें:",
                    parse_mode="Markdown",
                    reply_markup=build_negative_marking_submenu(user_id)
                )
                bot.answer_callback_query(call.id)
                return

            elif data == 'neg_sub_toggle':
                features["negative_marking_status"] = not features["negative_marking_status"]
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=build_negative_marking_submenu(user_id)
                )
                bot.answer_callback_query(call.id, "⚡ Status Toggled!")
                return

            elif data.startswith('neg_val_') and data != 'neg_val_custom':
                val_str = data.replace('neg_val_', '')
                features["negative_marking_value"] = float(val_str)
                features["negative_marking_status"] = True
                
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"✅ नेगेटिव मार्किंग `{val_str}` पर सेट कर दी गई है। मुख्य डैशबोर्ड पर लौट रहे हैं...",
                    parse_mode="Markdown"
                )
                # वापस मुख्य डैशबोर्ड दिखाएं
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="⚙️ *ADVANCED CREATOR BOT - EDIT FEATURE DASHBOARD* ⚙️",
                    parse_mode="Markdown",
                    reply_markup=build_main_dashboard_keyboard(user_id)
                )
                bot.answer_callback_query(call.id, f"Saved: {val_str}")
                return

            elif data == 'neg_val_custom':
                user_pending_inputs[user_id] = "WAITING_FOR_CUSTOM_NEG"
                bot.answer_callback_query(call.id, "कस्टम वैल्यू दर्ज करें")
                bot.send_message(
                    call.message.chat.id,
                    "✏️ कृपया चैट में अपनी पसंद की **कस्टम नेगेटिव मार्किंग वैल्यू** टाइप करके भेजें (जैसे: `0.15` या `0.40`):",
                    parse_mode="Markdown"
                )
                return

            # 3. सब-मेनू नेविगेशन (Timer Sub-menu)
            elif data == 'sub_timer_menu':
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="⏱️ *Per-Question Timer Configuration*\n\nहर सवाल के लिए उत्तर देने का समय चुनें:",
                    parse_mode="Markdown",
                    reply_markup=build_timer_submenu(user_id)
                )
                bot.answer_callback_query(call.id)
                return

            elif data == 'timer_sub_toggle':
                features["timer_per_q"] = not features["timer_per_q"]
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=build_timer_submenu(user_id)
                )
                bot.answer_callback_query(call.id, "⚡ Timer Status Toggled!")
                return

            elif data.startswith('timer_val_'):
                secs = int(data.replace('timer_val_', ''))
                features["timer_seconds"] = secs
                features["timer_per_q"] = True
                
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"⚙️ *ADVANCED CREATOR BOT - EDIT FEATURE DASHBOARD* ⚙️",
                    parse_mode="Markdown",
                    reply_markup=build_main_dashboard_keyboard(user_id)
                )
                bot.answer_callback_query(call.id, f"Timer set to {secs}s")
                return

            # 4. नेविगेशन और सेव एक्शंस
            elif data == 'feat_action_back_main':
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="⚙️ *ADVANCED CREATOR BOT - EDIT FEATURE DASHBOARD* ⚙️",
                    parse_mode="Markdown",
                    reply_markup=build_main_dashboard_keyboard(user_id)
                )
                bot.answer_callback_query(call.id)
                return

            elif data == 'feat_action_reset':
                reset_user_features(user_id)
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=build_main_dashboard_keyboard(user_id)
                )
                bot.answer_callback_query(call.id, "🔄 All settings reset to default!")
                return

            elif data == 'feat_action_close':
                bot.answer_callback_query(call.id, "Panel closed.")
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="❌ *Edit Feature Dashboard Closed.*\nदुबारा खोलने के लिए `/editfeature` टाइप करें।",
                    parse_mode="Markdown"
                )
                return

            elif data == 'feat_action_save':
                final_config = get_final_quiz_execution_config(user_id)
                success_text = (
                    "🎉 *SETTINGS LOCKED & SAVED SUCCESSFULLY!* 🚀\n\n"
                    f"📌 *Creator Bot Active Config Summary:*\n"
                    f"• Negative Marking : `{'ON (' + str(final_config['negative_marking_value']) + ')' if final_config['negative_marking_status'] else 'OFF'}`\n"
                    f"• Paid Quiz Mode   : `{'ON' if final_config['paid_quiz'] else 'OFF'}`\n"
                    f"• Detailed Expl    : `{'ON' if final_config['explanation'] else 'OFF'}`\n"
                    f"• Question Shuffle : `{'ON' if final_config['question_shuffling'] else 'OFF'}`\n"
                    f"• Question Timer   : `{'ON (' + str(final_config['timer_seconds']) + 's)' if final_config['timer_per_q'] else 'OFF'}`\n"
                    f"• Quiz Pattern     : `{'Practice Mode' if final_config['quiz_mode_type'] else 'Test Mode'}`\n\n"
                    "_अब यह अपडेटेड कॉन्फ़िगरेशन आपके क्रिएटर बॉट और क्विज़ इंजन से लिंक हो गया है!_ ✨"
                )
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=success_text,
                    parse_mode="Markdown"
                )
                bot.answer_callback_query(call.id, "🚀 Settings locked and saved!")

        except Exception as e:
            logger.error(f"Error in editfeature callback router: {e}")
            bot.answer_callback_query(call.id, "⚠️ An error occurred, please try again.")
