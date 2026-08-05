import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DocumentationConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (ROOT / "SKILL.md").read_text()
        cls.endpoints = (ROOT / "references" / "api_endpoints.md").read_text()
        cls.examples = (ROOT / "references" / "python_examples.md").read_text()
        cls.contracts = json.loads((ROOT / "references" / "operation_contracts.json").read_text())
        cls.live = json.loads((ROOT / "tests" / "fixtures" / "live_craigdemo_2026-08-05.json").read_text())

    def test_no_sql_percent_wildcard_examples(self):
        generated_examples = "\n".join((self.endpoints, self.examples))
        self.assertNotRegex(generated_examples, r'"Condition"\s*:\s*"LIKE [^"]*%')

    def test_full_text_example_uses_current_contract(self):
        section = self.examples.split("## Full-Text Search", 1)[1]
        self.assertIn('"Search": search_text', section)
        self.assertIn('"Categories":', section)
        self.assertIn('result.get("Results", [])', section)
        self.assertNotIn('"SearchText"', section)

    def test_wrapper_examples_do_not_use_unsupported_where_clause(self):
        self.assertNotRegex(self.examples, r'"WhereClause"\s*:')

    def test_complete_task_uses_generated_rest_contract(self):
        workflow = self.examples.split("## Workflow Task Management", 1)[1]
        self.assertIn('"TaskDecision": task_decision', workflow)
        self.assertNotRegex(workflow, r'"SelectedExitNo"\s*:')
        self.assertIn('"QueryMode": 0', workflow)
        self.assertIn('result.get("QueryResult", [])', workflow)
        self.assertNotIn('result.get("TaskInfos", [])', workflow)

    def test_all_rows_example_uses_explicit_int_max(self):
        section = self.examples.split("## Paginated Query (All Results)", 1)[1].split("## Get Category Info", 1)[0]
        self.assertIn('"MaxRows": 2147483647', section)

    def test_create_document_has_no_wrapper(self):
        for text in (self.skill, self.endpoints, self.examples):
            self.assertNotRegex(text, r'"TheDocument"\s*:')

    def test_contract_registry_is_well_formed(self):
        operations = self.contracts["operations"]
        self.assertEqual(operations["GetDocumentStream"]["method"], "POST")
        self.assertEqual(operations["GetSystemCustomerId"]["method"], "GET")
        self.assertEqual(operations["CompleteTask"]["required"], ["Comment", "TaskDecision", "TaskNo"])
        self.assertEqual(operations["ExecuteDependentFieldsQuery"]["response_root"], "QueryResult")
        self.assertIn("CaseDefinitionNo", operations["FillDependentFields"]["context_members"])

    def test_live_fixture_records_cleanup_and_server_scope(self):
        self.assertEqual(self.live["service"]["service_version"], "35.0.3.0")
        self.assertEqual(self.live["read_tests"]["max_rows"]["zero"], 500)
        self.assertTrue(self.live["write_tests"]["case_index_save"]["valid_reference_workflow"]["quick_save_read_back"])
        self.assertFalse(self.live["write_tests"]["case_index_save"]["retest_required"])
        self.assertTrue(self.live["write_tests"]["cleanup_verified"]["all_unavailable_after_cleanup"])


if __name__ == "__main__":
    unittest.main()
