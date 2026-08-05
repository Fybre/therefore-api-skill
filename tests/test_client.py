import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "references"))

from therefore_client import ThereforeAPIError, ThereforeClient, ThereforeConfig  # noqa: E402


class RecordingClient(ThereforeClient):
    def __init__(self):
        super().__init__(ThereforeConfig(base_url="https://acme.thereforeonline.com/restun", auth_method="basic", username="u", password="p"))
        self.calls = []
        self.responses = []

    def _post(self, path, payload, **kwargs):
        self.calls.append(("POST", path, payload))
        return self.responses.pop(0) if self.responses else {}

    def _get(self, path):
        self.calls.append(("GET", path, None))
        return self.responses.pop(0) if self.responses else {}


class FailingClient(ThereforeClient):
    def _open(self, req, timeout):
        body = json.dumps({
            "WSError": {
                "ErrorCodeString": "SyntaxError",
                "ErrorMessage": "bad condition",
                "ErrorId": "error-1",
            }
        }).encode()
        raise urllib.error.HTTPError(req.full_url, 500, "error", {}, io.BytesIO(body))

class ClientContractTests(unittest.TestCase):
    def setUp(self):
        self.client = RecordingClient()

    def test_cloud_tenant_is_derived_safely(self):
        self.assertEqual(self.client._headers()["TenantName"], "acme")
        other = ThereforeClient(ThereforeConfig(base_url="https://notthereforeonline.com/restun", auth_method="basic", username="u", password="p"))
        self.assertNotIn("TenantName", other._headers())

    def test_comment_payloads(self):
        self.client.add_comment(10, "hello")
        self.client.edit_comment(10, "guid", "edited")
        self.client.get_comments(10, max_count=25)
        self.assertEqual(self.client.calls[0], ("POST", "AddComment", {"ObjNo": 10, "ObjType": 2, "CommentText": "hello"}))
        self.assertEqual(self.client.calls[1], ("POST", "EditComment", {"ObjNo": 10, "ObjType": 2, "ID": "guid", "CommentText": "edited"}))
        self.assertEqual(self.client.calls[2], ("POST", "LoadComments", {"ObjNo": 10, "ObjType": 2, "MaxCount": 25}))

    def test_checkout_payloads_match_generated_contract(self):
        self.client.check_out_document(10)
        self.client.check_in_document(10, "updated")
        self.client.undo_check_out_document(10)
        self.assertEqual(self.client.calls[0], ("POST", "CheckOutDocument", {"DocNo": 10}))
        self.assertEqual(self.client.calls[1], ("POST", "CheckInDocument", {"DocNo": 10, "CheckInComment": "updated"}))
        self.assertEqual(self.client.calls[2], ("POST", "UndoCheckOutDocument", {"DocNo": 10}))

    def test_case_and_task_payloads(self):
        self.client.create_case(11)
        self.client.complete_task(99, 1, "approved")
        self.assertEqual(self.client.calls[0], ("POST", "CreateCase", {"CaseDefNo": 11}))
        self.assertEqual(self.client.calls[1], ("POST", "CompleteTask", {"TaskNo": 99, "TaskDecision": 1, "Comment": "approved"}))

    def test_case_lifecycle_payloads(self):
        self.client.get_case_definition(11)
        self.client.save_case_index_data_quick(92, [{"StringIndexData": {"FieldNo": 1, "DataValue": "x"}}])
        self.client.link_cases(92, 93)
        self.client.restore_deleted_case(92, restore_related_documents=True)
        self.assertEqual(self.client.calls[0][2]["CaseDefinitionNo"], 11)
        self.assertEqual(self.client.calls[1][1], "SaveCaseIndexDataQuick")
        self.assertEqual(self.client.calls[2][2], {"CaseNoA": 92, "CaseNoB": 93})
        self.assertEqual(self.client.calls[3][2], {"CaseNo": 92, "RestoreRelatedDocuments": True})

    def test_list_users_defaults_to_verified_flags(self):
        self.client.execute_users_query()
        self.assertEqual(self.client.calls[0], ("POST", "ExecuteUsersQuery", {"Flags": 4}))

    def test_get_objects_does_not_apply_a_permission_mask_by_default(self):
        self.client.get_objects()
        self.client.get_objects(role_access_mask=123, perm_type=8)
        self.assertEqual(self.client.calls[0], ("POST", "GetObjects", {"Flags": 0, "Type": 11}))
        self.assertEqual(self.client.calls[1][2], {"Flags": 0, "Type": 11, "RoleAccessMask": 123, "PermType": 8})

    def test_task_info_query_includes_required_modes(self):
        self.client.execute_task_info_query(max_rows=50)
        self.assertEqual(self.client.calls[0], ("POST", "ExecuteTaskInfoQuery", {"QueryMode": 0, "ViewMode": 0, "MaxRows": 50}))

    def test_stream_bytes_are_not_base64_decoded(self):
        self.client.responses = [{"FileData": [0, 1, 2, 255]}]
        self.assertEqual(self.client.get_document_stream(12), b"\x00\x01\x02\xff")
        self.assertEqual(self.client.calls[0][1], "GetDocumentStream")

    def test_call_endpoint_defaults_to_post_and_get_is_explicit(self):
        self.client.call_endpoint("GetDomainInfo")
        self.client.call_endpoint("GetSystemCustomerId", http_method="GET")
        self.assertEqual(self.client.calls[0][:2], ("POST", "GetDomainInfo"))
        self.assertEqual(self.client.calls[1][:2], ("GET", "GetSystemCustomerId"))

    def test_multi_query_merges_nested_query_results(self):
        fixture_dir = ROOT / "tests" / "fixtures"
        self.client.responses = [
            json.loads((fixture_dir / "multi_query_first.json").read_text()),
            json.loads((fixture_dir / "multi_query_next.json").read_text()),
            {},
        ]
        result = self.client.execute_async_multi_query_all([{"CategoryNo": 8}])
        rows = result["QueryResults"][0]["QueryResult"]["ResultRows"]
        self.assertEqual([row["DocNo"] for row in rows], [1, 2])
        self.assertEqual(result["TotalRows"], [2])
        self.assertEqual(self.client.calls[-1][1], "ReleaseMultiQuery")

    def test_structured_ws_error_is_preserved(self):
        client = FailingClient(ThereforeConfig(base_url="https://example.test/restun", auth_method="basic", username="u", password="p"))
        with self.assertRaises(ThereforeAPIError) as caught:
            client.get_connection_token()
        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(caught.exception.error_data["ErrorCodeString"], "SyntaxError")
        self.assertIn("bad condition", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
