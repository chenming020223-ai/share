import unittest

from worldcup_predictor.delivery import build_delivery_audit


class DeliveryAuditTest(unittest.TestCase):
    def test_delivery_audit_separates_product_delivery_from_live_money(self):
        audit = build_delivery_audit(
            run_tests=False,
            run_frontend_check=False,
            write_output=False,
        )

        self.assertEqual(audit["deliveryStatus"], "DELIVERABLE_RESEARCH_SYSTEM")
        self.assertFalse(audit["canUseRealMoney"])
        self.assertFalse(audit["formalEvEnabled"])
        self.assertTrue(any(item["label"] == "中文 Excel 报告" and item["passed"] for item in audit["checks"]))
        self.assertTrue(any(item["label"] == "中文 PDF 报告" and item["passed"] for item in audit["checks"]))


if __name__ == "__main__":
    unittest.main()
