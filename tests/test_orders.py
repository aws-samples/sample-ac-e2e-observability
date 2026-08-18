"""Unit test orders tool"""

import unittest
from unittest.mock import MagicMock
from app.fn_tool_orders import orders

mock_context_get_order_status = MagicMock()
mock_context_get_order_status.client_context.custom = {
    "bedrockAgentCoreToolName": "DemoGW___get_order_status",
}
mock_context_update_order_status = MagicMock()
mock_context_update_order_status.client_context.custom = {
    "bedrockAgentCoreToolName": "DemoGW___update_order_status",
}


class TestOrdersToolLambda(unittest.TestCase):
    """Test cases for Orders tool"""

    def test_get_order_status(self):
        """Test get order status"""
        mock_event = {"orderId": "72639"}
        response = orders.lambda_handler(
            mock_event,
            mock_context_get_order_status
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "Order Id 72639 is in shipped status")

    def test_update_order_status(self):
        """Test update order status"""
        mock_event = {
            "orderId": "124",
            "newStatus": "on-hold"
        }
        response = orders.lambda_handler(
            mock_event,
            mock_context_update_order_status,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            response["body"],
            "Updated Order Id 124 status to on-hold"
        )

    def test_unknown_tool(self):
        """Test unknown tool"""
        mock_context_unknown = MagicMock()
        mock_context_unknown.client_context.custom = {
            "bedrockAgentCoreToolName": "DemoGW___get_user_name",
        }
        mock_event = {"orderId": "99999"}
        response = orders.lambda_handler(
            mock_event,
            mock_context_unknown
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(response["body"], "Error: unknown tool 'get_user_name'")

    def test_get_order_status_missing_param(self):
        """Test get order status missing orderID"""
        mock_event = {}
        response = orders.lambda_handler(
            mock_event,
            mock_context_update_order_status,
        )
        self.assertEqual(response["statusCode"], 400)

    def test_update_order_status_missing_param(self):
        """Test update order status missing newStatus"""
        mock_event = {"orderId": "no_good_000"}
        response = orders.lambda_handler(
            mock_event,
            mock_context_update_order_status,
        )
        self.assertEqual(response["statusCode"], 400)

    def test_update_order_status_missing_context(self):
        """Test update order status missing newStatus"""
        mock_event = {"orderId": "no_good_000"}
        response = orders.lambda_handler(
            mock_event,
            None,
        )
        self.assertEqual(response["statusCode"], 400)

    def test_update_order_status_missing_gw_name(self):
        """Test tool name parsing"""
        mock_context = MagicMock()
        mock_context.client_context.custom = {
            "bedrockAgentCoreToolName": "get_user_name",
        }
        mock_event = {"orderId": "no_good_000"}
        response = orders.lambda_handler(
            mock_event,
            mock_context,
        )
        self.assertEqual(response["statusCode"], 400)

if __name__ == '__main__':
    unittest.main()

# LambdaContext([
#     aws_request_id=a307ab55-274e-4db7-ba85-5b5c3c2d7adf,
#     log_group_name=/aws/lambda/ac-oauth-demo-OrdersTool**********,
#     log_stream_name=2026/04/26/[$LATEST]346f3b3c62564cd5913a1cbf220b509b,
#     function_name=ac-oauth-demo-OrdersTool**********,
#     memory_limit_in_mb=128,
#     function_version=$LATEST,
#     invoked_function_arn=**********,
#     client_context=ClientContext([
#         custom={
#             'bedrockAgentCoreTargetId': 'DB*******',
#             'bedrockAgentCoreGatewayId': 'ac-oauth-demo-gw-******',
#             'bedrockAgentCoreMessageVersion': '1.0',
#             'bedrockAgentCoreMcpMessageId': '2',
#             'bedrockAgentCoreAwsRequestId': '19d**-**-**-**-*****',
#             'bedrockAgentCoreToolName': 'ac-oauth-demo-gwt-orders___get_order_status'
#         },
#         env=None,
#         client=None
#     ]),
#     identity=CognitoIdentity([cognito_identity_id=None,cognito_identity_pool_id=None]),
#     tenant_id=None
# ])
