from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def order_cancel_inline_keyboard(order_id: str) -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		inline_keyboard=[
			[
				InlineKeyboardButton(
					text="❌ Annuler cette commande",
					callback_data=f"cancel_order:{order_id}",
				),
			],
		],
	)
