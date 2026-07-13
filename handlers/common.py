from aiogram import Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext


common_router = Router()


@common_router.message(Command("start"))
async def start_handler(message: types.Message) -> None:
	keyboard = types.ReplyKeyboardMarkup(
		keyboard=[
			[
				types.KeyboardButton(text="📋 Passer une commande"),
			],
		],
		resize_keyboard=True,
		is_persistent=True,
	)
	await message.answer(
		"Bienvenue chez La Talemelerie ! 🥖\nPour passer une commande, utilisez le menu ci-dessous.",
		reply_markup=keyboard,
	)


@common_router.message(StateFilter("*"), Command("cancel"))
@common_router.message(StateFilter("*"), lambda message: message.text == "Annuler")
async def cancel_handler(message: types.Message, state: FSMContext) -> None:
	await state.clear()
	await message.answer(
		"Commande annulée.",
		reply_markup=types.ReplyKeyboardRemove(),
	)
