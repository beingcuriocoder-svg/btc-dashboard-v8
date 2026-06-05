from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import main

TOKEN = "YOUR_BOT_TOKEN"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = main.run_analysis()

        await update.message.reply_text(
            f"BTC Dashboard\n\n{result}"
        )

    except Exception as e:
        await update.message.reply_text(
            f"Error:\n{e}"
        )

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))

print("Bot Running...")
app.run_polling()