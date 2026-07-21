from notification_manager import TelegramNotifier


bot = TelegramNotifier()


bot.start(
    "Overgeared",
    256,
    300
)