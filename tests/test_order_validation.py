import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from handlers import order


PARIS_TZ = ZoneInfo("Europe/Paris")


class OrderValidationTests(unittest.TestCase):
    def _base_payload(self, pickup_datetime: str = "2026-01-05 10:30") -> dict:
        return {
            "customer_name": "Jean Dupont",
            "customer_phone": "+33612345678",
            "pickup_datetime": pickup_datetime,
            "items": [
                {
                    "name": "Croissant",
                    "quantity": 2,
                    "unit_price": 1.2,
                }
            ],
        }

    def test_rejects_pickup_more_than_60_days_ahead(self) -> None:
        payload = self._base_payload("2026-03-05 10:30")

        with (
            patch("handlers.order._now_paris", return_value=datetime(2026, 1, 1, 9, 0, tzinfo=PARIS_TZ)),
            patch.object(order.settings, "bakery_phone", "+33 1 23 45 67 89"),
        ):
            with self.assertRaises(ValueError) as ctx:
                order.validate_order_payload(payload)

        self.assertIn("au-delà de 60 jours", str(ctx.exception))
        self.assertIn("+33 1 23 45 67 89", str(ctx.exception))

    def test_rejects_pickup_outside_sunday_working_hours(self) -> None:
        payload = self._base_payload("2026-01-04 14:00")

        with patch("handlers.order._now_paris", return_value=datetime(2026, 1, 1, 9, 0, tzinfo=PARIS_TZ)):
            with self.assertRaises(ValueError) as ctx:
                order.validate_order_payload(payload)

        self.assertIn("Nos horaires de retrait", str(ctx.exception))

    def test_calculates_total_from_items_when_missing(self) -> None:
        payload = self._base_payload("2026-01-05 10:30")

        with patch("handlers.order._now_paris", return_value=datetime(2026, 1, 1, 9, 0, tzinfo=PARIS_TZ)):
            validated = order.validate_order_payload(payload)

        self.assertEqual(validated["name"], "Jean Dupont")
        self.assertEqual(validated["phone"], "+33612345678")
        self.assertEqual(validated["pickup_datetime"], "10h30 05-01-2026")
        self.assertEqual(validated["total_price"], 2.4)

    def test_rejects_invalid_phone(self) -> None:
        payload = self._base_payload()
        payload["customer_phone"] = "abc"

        with self.assertRaises(ValueError) as ctx:
            order.validate_order_payload(payload)

        self.assertIn("numéro de téléphone est invalide", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
