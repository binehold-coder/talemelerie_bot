import unittest
from unittest.mock import AsyncMock, patch

from handlers import order
from services.order_sheet_schema import (
    COL_ORDER_ID,
    COL_STATUS,
    COL_TELEGRAM_CHAT_ID,
    build_order_row,
)


def _make_row(order_id: str, chat_id: int, status: str) -> list[str]:
    return build_order_row(
        {
            COL_ORDER_ID: order_id,
            COL_TELEGRAM_CHAT_ID: str(chat_id),
            COL_STATUS: status,
        }
    )


class CancelOrderFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_order_rejects_empty_order_id(self) -> None:
        message = AsyncMock()

        with (
            patch("handlers.order._find_order_by_id", AsyncMock()) as find_mock,
            patch("handlers.order._cancel_order_in_sheet", AsyncMock()) as cancel_mock,
        ):
            await order._process_cancel_request(message, 12345, "   ")

        find_mock.assert_not_awaited()
        cancel_mock.assert_not_awaited()
        message.answer.assert_awaited_once_with("Veuillez saisir un numéro de commande valide.")

    async def test_cancel_order_returns_not_found_for_unknown_order_id(self) -> None:
        message = AsyncMock()

        with (
            patch("handlers.order._find_order_by_id", AsyncMock(return_value=None)) as find_mock,
            patch("handlers.order._cancel_order_in_sheet", AsyncMock()) as cancel_mock,
        ):
            await order._process_cancel_request(message, 12345, "LT-LMS-2026-07-999")

        find_mock.assert_awaited_once_with("LT-LMS-2026-07-999")
        cancel_mock.assert_not_awaited()
        message.answer.assert_awaited_once_with("Aucune commande trouvée pour ce numéro.")

    async def test_cancel_order_success_when_status_is_nouveau(self) -> None:
        message = AsyncMock()
        row = _make_row("LT-LMS-2026-07-001", 12345, "Nouveau")

        with (
            patch("handlers.order._find_order_by_id", AsyncMock(return_value=(2, row))),
            patch("handlers.order._cancel_order_in_sheet", AsyncMock(return_value=True)) as cancel_mock,
        ):
            await order._process_cancel_request(message, 12345, "LT-LMS-2026-07-001")

        cancel_mock.assert_awaited_once_with("LT-LMS-2026-07-001")
        message.answer.assert_awaited_once_with("✅ Votre commande a bien été annulée.")

    async def test_cancel_order_shows_phone_fallback_when_status_is_not_nouveau(self) -> None:
        message = AsyncMock()
        row = _make_row("LT-LMS-2026-07-002", 12345, "En préparation")

        with (
            patch("handlers.order._find_order_by_id", AsyncMock(return_value=(2, row))),
            patch("handlers.order._cancel_order_in_sheet", AsyncMock(return_value=True)) as cancel_mock,
            patch.object(order.settings, "bakery_phone", "+33 1 23 45 67 89"),
        ):
            await order._process_cancel_request(message, 12345, "LT-LMS-2026-07-002")

        cancel_mock.assert_not_awaited()
        message.answer.assert_awaited_once_with(
            "Votre commande ne peut plus être annulée automatiquement, car sa préparation peut déjà avoir commencé.\n"
            "Pour toute demande, appelez-nous :\n"
            "📞 +33 1 23 45 67 89"
        )

    async def test_cancel_order_rejects_order_from_another_chat(self) -> None:
        message = AsyncMock()
        row = _make_row("LT-LMS-2026-07-003", 99999, "Nouveau")

        with (
            patch("handlers.order._find_order_by_id", AsyncMock(return_value=(2, row))),
            patch("handlers.order._cancel_order_in_sheet", AsyncMock(return_value=True)) as cancel_mock,
        ):
            await order._process_cancel_request(message, 12345, "LT-LMS-2026-07-003")

        cancel_mock.assert_not_awaited()
        message.answer.assert_awaited_once_with("Cette commande ne vous appartient pas.")


if __name__ == "__main__":
    unittest.main()
