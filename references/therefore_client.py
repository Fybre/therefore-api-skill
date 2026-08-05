#!/usr/bin/env python3
"""Focused standalone REST reference client for the contracts documented in this skill.

This is not a vendored copy of the complete therefore-mcp client. Keep shared operation
payloads aligned with references/operation_contracts.json and test them in tests/test_client.py.
"""

import base64
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
import urllib.error
import socket
import sys
import time as _time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ThereforeAPIError(Exception):
    """HTTP failure returned by Therefore, preserving its structured WSError payload."""

    def __init__(
        self,
        endpoint: str,
        status: int,
        error_data: Optional[Dict[str, Any]] = None,
        response_body: str = '',
    ) -> None:
        self.endpoint = endpoint
        self.status = status
        self.error_data = error_data or {}
        self.response_body = response_body
        message = (
            self.error_data.get('ErrorMessage')
            or self.error_data.get('Message')
            or response_body
            or f'HTTP {status}'
        )
        code = self.error_data.get('ErrorCodeString') or self.error_data.get('ErrorCode')
        prefix = f'[{code}] ' if code is not None else ''
        super().__init__(f'{prefix}{message} (HTTP {status} from {endpoint})')


@dataclass
class ThereforeConfig:
    base_url: str
    auth_method: str
    username: Optional[str] = None
    password: Optional[str] = None
    tenant_name: Optional[str] = None
    timeout_seconds: int = 20
    workflow_timeout_seconds: Optional[int] = None
    workflow_max_rows: Optional[int] = None
    workflow_retry_timeout_seconds: Optional[int] = None
    workflow_retry_count: int = 0
    debug: bool = False


class _DebugRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that logs each hop when debug is enabled."""
    def __init__(self, log_fn):
        super().__init__()
        self._log = log_fn

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._log(f" -> {code} {msg} -> {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ThereforeClient:
    def __init__(self, config: ThereforeConfig):
        self.config = config
        self.base_url = config.base_url.rstrip('/')
        self.ctx = ssl.create_default_context()
        if config.debug:
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=self.ctx),
                _DebugRedirectHandler(self._log),
            )
        else:
            self._opener = None

    def _log(self, message: str) -> None:
        if self.config.debug:
            print(f"[THEREFORE] {message}", file=sys.stderr, flush=True)

    def _headers(self) -> Dict[str, str]:
        headers = {
            'Content-Type': 'application/json; charset=utf-8'
        }
        method = self.config.auth_method.lower()
        if method == 'basic':
            if not self.config.username or not self.config.password:
                raise ValueError('Basic auth requires username/password')
            token = base64.b64encode(
                f"{self.config.username}:{self.config.password}".encode('utf-8')
            ).decode('ascii')
            headers['Authorization'] = f'Basic {token}'
        elif method == 'bearer':
            if not self.config.password:
                raise ValueError('Bearer auth requires password (token)')
            headers['Authorization'] = f'Bearer {self.config.password}'
        tenant_name = self.config.tenant_name
        if not tenant_name:
            hostname = (urllib.parse.urlparse(self.base_url).hostname or '').lower()
            if hostname.endswith('.thereforeonline.com'):
                tenant_name = hostname.split('.')[0]
        if tenant_name:
            headers['TenantName'] = tenant_name
        return headers

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return True
        if isinstance(exc, urllib.error.URLError):
            reason = getattr(exc, 'reason', '')
            if reason and 'timed out' in str(reason).lower():
                return True
        return False

    def _open(self, req, timeout):
        if self._opener:
            return self._opener.open(req, timeout=timeout)
        return urllib.request.urlopen(req, context=self.ctx, timeout=timeout)

    def _post(
        self,
        path: str,
        payload: Dict[str, Any],
        timeout_override: Optional[int] = None,
        retry_timeout_override: Optional[int] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{path}"
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        for k, v in self._headers().items():
            req.add_header(k, v)
        self._log(f"POST {url} ({len(data)} bytes)")
        base_timeout = self.config.timeout_seconds
        if timeout_override is not None:
            try:
                base_timeout = max(1, int(timeout_override))
            except ValueError:
                base_timeout = self.config.timeout_seconds
        retry_timeout = retry_timeout_override
        if retry_timeout is None and retry_count:
            retry_timeout = max(base_timeout * 2, base_timeout + 30)
        if retry_timeout is not None:
            try:
                retry_timeout = max(1, int(retry_timeout))
            except ValueError:
                retry_timeout = base_timeout
        timeouts = [base_timeout]
        for _ in range(max(0, int(retry_count))):
            timeouts.append(retry_timeout or base_timeout)
        last_exc: Optional[Exception] = None
        for attempt, timeout in enumerate(timeouts, start=1):
            if attempt > 1:
                self._log(f" retry {attempt}/{len(timeouts)} (timeout={timeout}s)")
            t0 = _time.monotonic()
            try:
                with self._open(req, timeout=timeout) as r:
                    body = r.read().decode('utf-8', errors='replace')
                elapsed_ms = (_time.monotonic() - t0) * 1000
                self._log(f" <- {r.status} {r.reason} ({len(body)} bytes, {elapsed_ms:.0f}ms)")
                return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                elapsed_ms = (_time.monotonic() - t0) * 1000
                try:
                    body = exc.read().decode('utf-8', errors='replace')
                except Exception:
                    body = ''
                detail = ''
                error_data: Dict[str, Any] = {}
                if body:
                    try:
                        err_json = json.loads(body)
                        error_data = err_json.get('WSError') or err_json
                        detail = (
                            error_data.get('ErrorMessage')
                            or error_data.get('Message')
                            or error_data.get('message')
                            or error_data.get('error')
                            or body
                        )
                    except (json.JSONDecodeError, AttributeError):
                        detail = body
                self._log(f" <- {exc.code} {detail!r} ({len(body)} bytes, {elapsed_ms:.0f}ms)")
                raise ThereforeAPIError(path, exc.code, error_data, body) from None
            except Exception as exc:
                elapsed_ms = (_time.monotonic() - t0) * 1000
                self._log(f" <- ERROR {type(exc).__name__}: {exc} ({elapsed_ms:.0f}ms)")
                last_exc = exc
                if not self._is_timeout_error(exc) or attempt >= len(timeouts):
                    raise
                continue
        if last_exc:
            raise last_exc
        return {}

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}/{path}"
        req = urllib.request.Request(url, method='GET')
        for k, v in self._headers().items():
            req.add_header(k, v)
        self._log(f"GET {url}")
        t0 = _time.monotonic()
        try:
            with self._open(req, timeout=self.config.timeout_seconds) as r:
                body = r.read().decode('utf-8', errors='replace')
            elapsed_ms = (_time.monotonic() - t0) * 1000
            self._log(f" <- {r.status} {r.reason} ({len(body)} bytes, {elapsed_ms:.0f}ms)")
            return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            elapsed_ms = (_time.monotonic() - t0) * 1000
            try:
                body = exc.read().decode('utf-8', errors='replace')
            except Exception:
                body = ''
            detail = ''
            error_data: Dict[str, Any] = {}
            if body:
                try:
                    err_json = json.loads(body)
                    error_data = err_json.get('WSError') or err_json
                    detail = (
                        error_data.get('ErrorMessage')
                        or error_data.get('Message')
                        or error_data.get('message')
                        or error_data.get('error')
                        or body
                    )
                except (json.JSONDecodeError, AttributeError):
                    detail = body
            self._log(f" <- {exc.code} {detail!r} ({len(body)} bytes, {elapsed_ms:.0f}ms)")
            raise ThereforeAPIError(path, exc.code, error_data, body) from None

    def get_category_info(self, category_no: int) -> Dict[str, Any]:
        return self._post('GetCategoryInfo', {
            'CategoryNo': category_no,
            'IsSearchFieldOrderNeeded': True,
            'IsAccessMaskNeeded': True,
        })

    def get_categories_tree(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._post('GetCategoriesTree', payload or {})

    def get_document(
        self,
        doc_no: int,
        include_index_data: bool = True,
        include_streams_info: bool = False,
        include_streams_data: bool = False,
        include_checkout_status: bool = False,
        include_access_mask: bool = False,
    ) -> Dict[str, Any]:
        return self._post('GetDocument', {
            'DocNo': doc_no,
            'IsCheckOutStatusNeeded': include_checkout_status,
            'IsIndexDataValuesNeeded': include_index_data,
            'IsStreamsInfoAndDataNeeded': include_streams_data,
            'IsStreamsInfoNeeded': include_streams_info,
            'IsAccessMaskNeeded': include_access_mask,
            'TitleHideCategory': False,
            'IsStreamDataBase64JSONNeeded': include_streams_data,
            'TitleType': 0,
            'RetrieveReason': '',
        })

    def preprocess_index_data(
        self,
        category_no: int,
        index_data_items: List[Dict[str, Any]],
        fill_dependent_fields: bool = True,
        reset_to_defaults: bool = True,
        do_calculate_fields: bool = True,
        get_auto_append_ix_data: bool = False,
        exclude_redundant: bool = True,
    ) -> Dict[str, Any]:
        return self._post('PreprocessIndexData', {
            'CategoryNo': category_no,
            'ExcludeReduntantForFillDependentFields': exclude_redundant,
            'FillDependentFields': fill_dependent_fields,
            'GetAutoAppendIxData': get_auto_append_ix_data,
            'ResetToDefaults': reset_to_defaults,
            'DoCalculateFields': do_calculate_fields,
            'IndexData': {
                'IndexDataItems': index_data_items,
            },
        })

    def evaluate_conditional_properties(
        self,
        category_no: int,
        index_data_items: List[Dict[str, Any]],
        changed_field_nos: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        return self._post('EvaluateConditionalProperties', {
            'IndexDataItems': index_data_items,
            'CategoryNo': category_no,
            'ChangedFieldNos': changed_field_nos or [],
        })

    def execute_dependent_fields_query(
        self,
        field_no: int,
        index_data_items: List[Dict[str, Any]],
        case_definition_no: int = 0,
        category_no: int = 0,
        max_rows: int = 500,
        save_mode: bool = False,
    ) -> Dict[str, Any]:
        """Return valid referenced values for a field in the current index-data context."""
        return self._post('ExecuteDependentFieldsQuery', {
            'CaseDefinitionNo': int(case_definition_no),
            'CategoryNo': int(category_no),
            'FieldNo': int(field_no),
            'IndexDataItems': index_data_items,
            'MaxRows': int(max_rows),
            'SaveMode': bool(save_mode),
        })

    def fill_dependent_fields(
        self,
        index_data_items: List[Dict[str, Any]],
        primary_field_no: int,
        *,
        doc_no: Optional[int] = None,
        case_definition_no: Optional[int] = None,
        category_no: Optional[int] = None,
        exclude_redundant: bool = False,
        include_access_mask: bool = False,
        do_calculate_fields: bool = True,
    ) -> Dict[str, Any]:
        """Resolve dependent values in exactly one document, case, or category context."""
        contexts = [doc_no is not None, case_definition_no is not None, category_no is not None]
        if sum(contexts) != 1:
            raise ValueError('Specify exactly one of doc_no, case_definition_no, or category_no')
        payload: Dict[str, Any] = {
            'IndexDataItems': index_data_items,
            'ExcludeRedundant': bool(exclude_redundant),
            'PrimaryFieldNo': int(primary_field_no),
            'IsAccessMaskNeeded': bool(include_access_mask),
            'DoCalculateFields': bool(do_calculate_fields),
        }
        if doc_no is not None:
            payload['DocNo'] = int(doc_no)
        elif case_definition_no is not None:
            payload['CaseDefinitionNo'] = int(case_definition_no)
        else:
            payload['CategoryNo'] = int(category_no)
        return self._post('FillDependentFields', payload)

    def create_document(
        self,
        category_no: int,
        streams: List[Dict[str, Any]],
        index_data_items: Optional[List[Dict[str, Any]]] = None,
        check_in_comments: str = '',
        with_auto_append_mode: int = 0,
        do_fill_dependent_fields: bool = True,
        run_webclient_flow: bool = True,
        persist_evaluate_response_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a document. When run_webclient_flow=True (default), runs the full
        4-step flow: GetCategoryInfo -> PreprocessIndexData ->
        EvaluateConditionalProperties -> CreateDocument.

        Returns dict with keys: category_info, preprocess_index_data,
        evaluate_conditional_properties, create_document.
        The created DocNo is at result['create_document']['DocNo'].
        """
        category_info = None
        preprocess_resp = None
        evaluate_resp = None
        effective_index_items = index_data_items or []
        if run_webclient_flow:
            category_info = self.get_category_info(category_no)
            preprocess_resp = self.preprocess_index_data(
                category_no=category_no,
                index_data_items=effective_index_items,
                fill_dependent_fields=True,
                reset_to_defaults=True,
                do_calculate_fields=True,
                get_auto_append_ix_data=False,
                exclude_redundant=True,
            )
            effective_index_items = (
                (preprocess_resp.get('IndexData') or {}).get('IndexDataItems')
            ) or []
            evaluate_resp = self.evaluate_conditional_properties(
                category_no=category_no,
                index_data_items=effective_index_items,
                changed_field_nos=[],
            )
            if persist_evaluate_response_path:
                with open(persist_evaluate_response_path, 'w', encoding='utf-8') as f:
                    json.dump(evaluate_resp, f, indent=2)
        create_payload = {
            'CategoryNo': category_no,
            'CheckInComments': check_in_comments,
            'IndexDataItems': effective_index_items,
            'Streams': streams,
            'DoFillDependentFields': do_fill_dependent_fields,
            'WithAutoAppendMode': with_auto_append_mode,
        }
        create_resp = self._post('CreateDocument', create_payload)
        return {
            'category_info': category_info,
            'preprocess_index_data': preprocess_resp,
            'evaluate_conditional_properties': evaluate_resp,
            'create_document': create_resp,
        }

    def delete_document(self, doc_no: int) -> Dict[str, Any]:
        return self._post('DeleteDocument', {'DocNo': doc_no})

    def check_out_document(self, doc_no: int) -> Dict[str, Any]:
        return self._post('CheckOutDocument', {'DocNo': doc_no})

    def check_in_document(self, doc_no: int, check_in_comment: Optional[str] = None) -> Dict[str, Any]:
        """Finish an existing checkout after replacement content has been opened/uploaded."""
        payload = {'DocNo': doc_no}
        if check_in_comment is not None:
            payload['CheckInComment'] = check_in_comment
        return self._post('CheckInDocument', payload)

    def undo_check_out_document(self, doc_no: int) -> Dict[str, Any]:
        return self._post('UndoCheckOutDocument', {'DocNo': doc_no})

    def add_comment(self, doc_no: int, comment_text: str, obj_type: int = 2) -> Dict[str, Any]:
        return self._post('AddComment', {
            'ObjNo': doc_no,
            'ObjType': obj_type,
            'CommentText': comment_text,
        })

    def edit_comment(self, doc_no: int, comment_id: str, comment_text: str, obj_type: int = 2) -> Dict[str, Any]:
        return self._post('EditComment', {
            'ObjNo': doc_no,
            'ObjType': obj_type,
            'ID': comment_id,
            'CommentText': comment_text,
        })

    def get_comments(self, doc_no: int, obj_type: int = 2, max_count: int = 100) -> Dict[str, Any]:
        return self._post('LoadComments', {
            'ObjNo': doc_no,
            'ObjType': obj_type,
            'MaxCount': max_count,
        })

    def complete_task(self, task_no: int, task_decision: int, comment: str = '') -> Dict[str, Any]:
        return self._post('CompleteTask', {
            'TaskNo': task_no,
            'TaskDecision': task_decision,
            'Comment': comment,
        })

    def claim_workflow_instance(self, workflow_instance_token: str, task_no: Optional[int] = None) -> Dict[str, Any]:
        payload = {'WorkflowInstanceToken': workflow_instance_token}
        if task_no is not None:
            payload['TaskNo'] = task_no
        return self._post('ClaimWorkflowInstance', payload)

    def disclaim_workflow_instance(self, workflow_instance_token: str, task_no: Optional[int] = None) -> Dict[str, Any]:
        payload = {'WorkflowInstanceToken': workflow_instance_token}
        if task_no is not None:
            payload['TaskNo'] = task_no
        return self._post('DisclaimWorkflowInstance', payload)

    def delegate_workflow_instance(self, workflow_instance_token: str, user_id: int, task_no: Optional[int] = None) -> Dict[str, Any]:
        payload = {'WorkflowInstanceToken': workflow_instance_token, 'UserId': user_id}
        if task_no is not None:
            payload['TaskNo'] = task_no
        return self._post('DelegateWorkflowInstance', payload)

    def get_case_definition(self, case_definition_no: int) -> Dict[str, Any]:
        return self._post('GetCaseDefinition', {
            'CaseDefinitionNo': int(case_definition_no),
            'IsAccessMaskNeeded': False,
            'IsSearchFieldOrderNeeded': False,
        })

    def create_case(self, case_definition_no: int, index_data_items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        payload = {'CaseDefNo': case_definition_no}
        if index_data_items is not None:
            payload['IndexDataItems'] = index_data_items
        return self._post('CreateCase', payload)

    def get_case(self, case_no: int) -> Dict[str, Any]:
        return self._post('GetCase', {'CaseNo': case_no})

    def get_case_documents(self, case_no: int, max_rows: int = 1000) -> Dict[str, Any]:
        return self._post('GetCaseDocuments', {'CaseNo': case_no, 'MaxRows': max_rows})

    def get_case_history(self, case_no: int) -> Dict[str, Any]:
        return self._post('GetCaseHistory', {'CaseNo': case_no})

    def save_case_index_data(
        self,
        case_no: int,
        index_data_items: List[Dict[str, Any]],
        last_change_time: str,
        last_change_time_iso: Optional[str] = None,
        check_in_comments: str = '',
    ) -> Dict[str, Any]:
        index_data: Dict[str, Any] = {
            'IndexDataItems': index_data_items,
            'LastChangeTime': last_change_time,
            'DoFillDependentFields': True,
        }
        if last_change_time_iso:
            index_data['LastChangeTimeISO8601'] = last_change_time_iso
        return self._post('SaveCaseIndexData', {
            'CaseNo': int(case_no),
            'CheckInComments': check_in_comments,
            'IndexData': index_data,
        })

    def save_case_index_data_quick(self, case_no: int, index_data_items: List[Dict[str, Any]], check_in_comments: str = '') -> Dict[str, Any]:
        return self._post('SaveCaseIndexDataQuick', {
            'CaseNo': int(case_no),
            'CheckInComments': check_in_comments,
            'IndexData': {'IndexDataItems': index_data_items},
        })

    def link_case_to_document(self, case_no: int, doc_no: int) -> Dict[str, Any]:
        return self._post('LinkCaseToDocument', {'CaseNo': int(case_no), 'DocNo': int(doc_no)})

    def link_cases(self, case_no_a: int, case_no_b: int) -> Dict[str, Any]:
        return self._post('LinkCases', {'CaseNoA': int(case_no_a), 'CaseNoB': int(case_no_b)})

    def unlink_cases(self, case_no_a: int, case_no_b: int) -> Dict[str, Any]:
        return self._post('UnlinkCases', {'CaseNoA': int(case_no_a), 'CaseNoB': int(case_no_b)})

    def close_case(self, case_no: int) -> Dict[str, Any]:
        return self._post('CloseCase', {'CaseNo': int(case_no)})

    def reopen_case(self, case_no: int) -> Dict[str, Any]:
        return self._post('ReopenCase', {'CaseNo': int(case_no)})

    def delete_case(self, case_no: int) -> Dict[str, Any]:
        return self._post('DeleteCase', {'CaseNo': int(case_no)})

    def restore_deleted_case(self, case_no: int, restore_related_documents: bool = False) -> Dict[str, Any]:
        return self._post('RestoreDeletedCase', {
            'CaseNo': int(case_no),
            'RestoreRelatedDocuments': bool(restore_related_documents),
        })

    def create_user(self, user_name: str, full_name: str, email: Optional[str] = None, password: Optional[str] = None, domain_name: Optional[str] = None) -> Dict[str, Any]:
        payload = {'UserName': user_name, 'FullName': full_name}
        if email is not None:
            payload['EMail'] = email
        if password is not None:
            payload['Password'] = password
        if domain_name is not None:
            payload['DomainName'] = domain_name
        return self._post('CreateUser', payload)

    def update_user_group_assignment(self, user_id: int, group_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        payload = {'UserId': user_id}
        if group_ids is not None:
            payload['GroupIds'] = group_ids
        return self._post('UpdateUserGroupAssignment', payload)

    def get_user_group_assignment(self, user_id: int) -> Dict[str, Any]:
        return self._post('GetUserGroupNo', {'UserId': user_id})

    def set_user_password(self, user_id: int, new_password: str) -> Dict[str, Any]:
        return self._post('SetUserPassword', {'UserId': user_id, 'NewPassword': new_password})

    def change_user_password(self, old_password: str, new_password: str) -> Dict[str, Any]:
        return self._post('ChangeUserPassword', {'OldPassword': old_password, 'NewPassword': new_password})

    def reset_user_password(self, user_id: int, send_email: bool = True) -> Dict[str, Any]:
        return self._post('ResetUserPwd', {'UserId': user_id, 'SendEmail': send_email})

    def delete_portal_user(self, user_id: int) -> Dict[str, Any]:
        return self._post('DeletePortalUser', {'UserId': user_id})

    def save_portal_user(self, user_id: int, user_name: Optional[str] = None, full_name: Optional[str] = None, email: Optional[str] = None, is_active: Optional[bool] = None) -> Dict[str, Any]:
        payload = {'UserId': user_id}
        if user_name is not None:
            payload['UserName'] = user_name
        if full_name is not None:
            payload['FullName'] = full_name
        if email is not None:
            payload['EMail'] = email
        if is_active is not None:
            payload['IsActive'] = is_active
        return self._post('SavePortalUser', payload)

    def move_user_license(self, source_user_id: int, target_user_id: int) -> Dict[str, Any]:
        return self._post('MoveUserLicense', {'SourceUserId': source_user_id, 'TargetUserId': target_user_id})

    def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        return self._post('GetUserSettings', {'UserId': user_id})

    def set_user_settings(self, user_id: int, settings: Dict[str, Any]) -> Dict[str, Any]:
        payload = {'UserId': user_id}
        payload.update(settings)
        return self._post('SetUserSettings', payload)

    def get_document_versions(self, doc_no: int) -> Dict[str, Any]:
        return self._post('GetDocumentHistory', {'DocNo': doc_no})  # GetDocumentVersions does not exist; use GetDocumentHistory

    def get_referenced_table_info(self, data_type_no: int) -> Dict[str, Any]:
        return self._post('GetReferencedTableInfo', {'DataTypeNo': data_type_no})

    def get_objects(self, flags: int = 0, obj_type: int = 11, role_access_mask: Optional[int] = None, perm_type: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'Flags': int(flags), 'Type': int(obj_type)}
        if role_access_mask is not None:
            payload['RoleAccessMask'] = int(role_access_mask)
        if perm_type is not None:
            payload['PermType'] = int(perm_type)
        return self._post('GetObjects', payload)

    def get_document_index_data(self, doc_no: int) -> Dict[str, Any]:
        return self._post('GetDocumentIndexData', {
            'DocNo': doc_no,
            'IsAccessMaskNeeded': False,
            'TitleHideCategory': False,
            'TitleType': 0,
        })

    def get_web_api_server_version(self) -> Dict[str, Any]:
        return self._post('GetWebAPIServerVersion', {})

    def get_connection_token(self) -> Dict[str, Any]:
        return self._post('GetConnectionToken', {})

    def get_domain_info(self) -> Dict[str, Any]:
        return self._post('GetDomainInfo', {})

    def get_client_discovery_info(self) -> Dict[str, Any]:
        return self._post('GetClientDiscoveryInfo', {})

    def get_connected_user(self, create: bool = False) -> Dict[str, Any]:
        return self._post('GetConnectedUser', {'Create': bool(create)})

    def get_system_customer_id(self) -> Dict[str, Any]:
        return self._get('GetSystemCustomerId')

    def get_permission_constants(self) -> Dict[str, Any]:
        return self._post('GetPermissionConstants', {})

    def get_role_permission_constants(self) -> Dict[str, Any]:
        return self._post('GetRolePermissionConstants', {})

    def get_document_properties(self, doc_no: int, version_no: int = 0, is_doc_title_needed: bool = False) -> Dict[str, Any]:
        return self._post('GetDocumentProperties', {'DocNo': doc_no, 'VersionNo': version_no, 'IsDocTitleNeeded': is_doc_title_needed})

    def get_document_history(self, doc_no: int) -> Dict[str, Any]:
        return self._post('GetDocumentHistory', {'DocNo': doc_no})

    def get_document_checkout_status(self, doc_no: int) -> Dict[str, Any]:
        return self._post('GetDocumentCheckoutStatus', {'DocNo': doc_no})

    def get_objects_list(self, load_items_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._post('GetObjectsList', {'LoadItemsList': load_items_list})

    def execute_users_query(self, query: Optional[str] = None, domain_names: Optional[List[str]] = None, flags: int = 4) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'Flags': int(flags)}
        if query is not None:
            payload['Query'] = query
        if domain_names is not None:
            payload['DomainNames'] = domain_names
        return self._post('ExecuteUsersQuery', payload)

    def get_users_from_group(self, group_id: Optional[int] = None, group_name: Optional[str] = None, domain_name: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if group_id is not None:
            payload['GroupId'] = int(group_id)
        if group_name:
            payload['GroupName'] = group_name
        if domain_name:
            payload['DomainName'] = domain_name
        return self._post('GetUsersFromGroup', payload)

    def get_user_details(self, user_or_group_id: int) -> Dict[str, Any]:
        return self._post('GetUserDetails', {'UserOrGroupId': int(user_or_group_id)})

    def get_keywords_by_field_no(self, field_no: int, category_no: Optional[int] = None, case_definition_no: Optional[int] = None, dependent_field_filter_value: Optional[str] = None, show_deactivated_keywords: Optional[bool] = None, index_data_items: Optional[List[Dict[str, Any]]] = None, skip_loading_keyword_nos: Optional[bool] = None, max_rows: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'FieldNo': int(field_no)}
        if category_no is not None:
            payload['CategoryNo'] = int(category_no)
        if case_definition_no is not None:
            payload['CaseDefinitionNo'] = int(case_definition_no)
        if dependent_field_filter_value is not None:
            payload['DependentFieldFilterValue'] = dependent_field_filter_value
        if show_deactivated_keywords is not None:
            payload['ShowDeactivatedKeywords'] = bool(show_deactivated_keywords)
        if index_data_items is not None:
            payload['IndexDataItems'] = index_data_items
        if skip_loading_keyword_nos is not None:
            payload['SkipLoadingKeywordNos'] = bool(skip_loading_keyword_nos)
        if max_rows is not None:
            payload['MaxRows'] = int(max_rows)
        return self._post('GetKeywordsByFieldNo', payload)

    def get_keywords_by_key_dic(self, key_dic_no: int, filter_value: Optional[str] = None, max_values: Optional[int] = None, include_deactivated_keywords: Optional[bool] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'KeyDicNo': int(key_dic_no)}
        if filter_value is not None:
            payload['FilterValue'] = filter_value
        if max_values is not None:
            payload['MaxValues'] = int(max_values)
        if include_deactivated_keywords is not None:
            payload['IncludeDeactivatedKeywords'] = bool(include_deactivated_keywords)
        return self._post('GetKeywordsByKeyDic', payload)

    def validate_keywords(self, field_no: int, keywords: List[str], is_filter_mode: Optional[bool] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'FieldNo': int(field_no), 'KeywordsToValidate': keywords}
        if is_filter_mode is not None:
            payload['IsFilterMode'] = bool(is_filter_mode)
        return self._post('ValidateKeywords', payload)

    def add_dictionary_keyword(self, dictionary_no: Optional[int], keyword_name: str, dictionary_type_no: Optional[int] = None, is_keyword_deactivated: Optional[bool] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'KeywordName': keyword_name}
        if dictionary_no is not None:
            payload['ByDictionaryID'] = int(dictionary_no)
        if dictionary_type_no is not None:
            payload['ByDictionaryTypeNo'] = int(dictionary_type_no)
        if is_keyword_deactivated is not None:
            payload['IsKeywordDeactivated'] = bool(is_keyword_deactivated)
        return self._post('AddDictionaryKeyword', payload)

    def update_dictionary_keyword(self, dictionary_no: Optional[int], keyword_id: int, keyword_name: Optional[str] = None, dictionary_type_no: Optional[int] = None, is_keyword_deactivated: Optional[bool] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'KeywordID': int(keyword_id)}
        if dictionary_no is not None:
            payload['ByDictionaryID'] = int(dictionary_no)
        if dictionary_type_no is not None:
            payload['ByDictionaryTypeNo'] = int(dictionary_type_no)
        if keyword_name is not None:
            payload['KeywordName'] = keyword_name
        if is_keyword_deactivated is not None:
            payload['IsKeywordDeactivated'] = bool(is_keyword_deactivated)
        return self._post('UpdateDictionaryKeyword', payload)

    def delete_dictionary_keyword(self, dictionary_no: Optional[int], keyword_id: int, dictionary_type_no: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'KeywordID': int(keyword_id)}
        if dictionary_no is not None:
            payload['ByDictionaryID'] = int(dictionary_no)
        if dictionary_type_no is not None:
            payload['ByDictionaryTypeNo'] = int(dictionary_type_no)
        return self._post('DeleteDictionaryKeyword', payload)

    def execute_workflow_query_for_all(self, workflow_flags: int = 0, max_rows: int = 1000) -> Dict[str, Any]:
        return self._post('ExecuteWorkflowQueryForAll', {'WorkflowFlags': int(workflow_flags), 'MaxRows': int(max_rows)}, timeout_override=self.config.workflow_timeout_seconds, retry_timeout_override=self.config.workflow_retry_timeout_seconds, retry_count=self.config.workflow_retry_count)

    def execute_task_info_query(self, query_mode: int = 0, view_mode: int = 0, max_rows: int = 1000, task_no: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'QueryMode': int(query_mode),
            'ViewMode': int(view_mode),
            'MaxRows': int(max_rows),
        }
        if task_no is not None:
            payload['TaskNo'] = int(task_no)
        return self._post('ExecuteTaskInfoQuery', payload)

    def execute_workflow_query_for_process(self, process_no: int, workflow_flags: int = 0, max_rows: int = 1000) -> Dict[str, Any]:
        return self._post('ExecuteWorkflowQueryForProcess', {'ProcessNo': int(process_no), 'WorkflowFlags': int(workflow_flags), 'MaxRows': int(max_rows)}, timeout_override=self.config.workflow_timeout_seconds, retry_timeout_override=self.config.workflow_retry_timeout_seconds, retry_count=self.config.workflow_retry_count)

    def get_linked_workflows_for_doc(self, doc_no: int, wf_doc_link_type: int = 0) -> Dict[str, Any]:
        return self._post('GetLinkedWorkflowsForDoc', {'DocNo': int(doc_no), 'WFDocLinkType': int(wf_doc_link_type)}, timeout_override=self.config.workflow_timeout_seconds, retry_timeout_override=self.config.workflow_retry_timeout_seconds, retry_count=self.config.workflow_retry_count)

    def get_workflow_history(self, instance_no: int, block_size: int = 1000, include_routing_info: bool = True, max_creation_date: Optional[str] = None, seq_pos: int = 0) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'BlockSize': int(block_size), 'IncludeRoutingInfo': bool(include_routing_info), 'InstanceNo': int(instance_no), 'SeqPos': int(seq_pos)}
        if max_creation_date:
            payload['MaxCreationDate'] = max_creation_date
        return self._post('GetWorkflowHistory', payload, timeout_override=self.config.workflow_timeout_seconds, retry_timeout_override=self.config.workflow_retry_timeout_seconds, retry_count=self.config.workflow_retry_count)

    def get_workflow_instance(self, instance_no: int, token_no: int = 0, is_access_mask_needed: bool = False, load_history: bool = False) -> Dict[str, Any]:
        return self._post('GetWorkflowInstance', {'InstanceNo': int(instance_no), 'TokenNo': int(token_no), 'IsAccessMaskNeeded': bool(is_access_mask_needed), 'LoadHistory': bool(load_history)}, timeout_override=self.config.workflow_timeout_seconds, retry_timeout_override=self.config.workflow_retry_timeout_seconds, retry_count=self.config.workflow_retry_count)

    def get_workflow_process(self, process_no: int, version_no: int = 0, load_tasks: bool = True, is_access_mask_needed: bool = False) -> Dict[str, Any]:
        return self._post('GetWorkflowProcess', {'ProcessNo': int(process_no), 'VersionNo': int(version_no), 'LoadTasks': bool(load_tasks), 'IsAccessMaskNeeded': bool(is_access_mask_needed)}, timeout_override=self.config.workflow_timeout_seconds, retry_timeout_override=self.config.workflow_retry_timeout_seconds, retry_count=self.config.workflow_retry_count)

    def get_workflow_task_settings(self, task_no: int, process_no: int, version_no: int = 0, setting_names: Optional[List[str]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'TaskNo': int(task_no), 'ProcessNo': int(process_no), 'VersionNo': int(version_no), 'SettingNames': setting_names or []}
        return self._post('GetWorkflowTaskSettings', payload, timeout_override=self.config.workflow_timeout_seconds, retry_timeout_override=self.config.workflow_retry_timeout_seconds, retry_count=self.config.workflow_retry_count)

    def execute_single_query(self, query: Dict[str, Any], full_text: Optional[str] = None) -> Dict[str, Any]:
        query_payload = dict(query)
        if int(query_payload.get('CaseDefinitionNo') or 0) == 0:
            query_payload.pop('CaseDefinitionNo', None)
        payload = {'Query': query_payload}
        if full_text is not None:
            payload['FullText'] = full_text
        return self._post('ExecuteSingleQuery', payload)

    def execute_async_single_query(self, query: Dict[str, Any], full_text: Optional[str] = None) -> Dict[str, Any]:
        query_payload = dict(query)
        if int(query_payload.get('CaseDefinitionNo') or 0) == 0:
            query_payload.pop('CaseDefinitionNo', None)
        payload = {'Query': query_payload}
        if full_text is not None:
            payload['FullText'] = full_text
        return self._post('ExecuteAsyncSingleQuery', payload)

    def get_next_single_query_rows(self, query_id: int, row_block_size: int) -> Dict[str, Any]:
        return self._post('GetNextSingleQueryRows', {'QueryID': query_id, 'RowBlockSize': row_block_size})

    def release_single_query(self, query_id: int) -> Dict[str, Any]:
        return self._post('ReleaseSingleQuery', {'QueryID': query_id})

    def execute_async_single_query_all(
        self,
        query: Dict[str, Any],
        full_text: Optional[str] = None,
        row_block_size: int = 1000,
        max_rows: int = 2147483647,
    ) -> Dict[str, Any]:
        """
        Execute async query and automatically page through ALL results.
        Handles QueryId (lowercase d) from ExecuteAsyncSingleQuery response,
        then uses QueryID (uppercase D) for GetNextSingleQueryRows.
        Always releases the query in a finally block.

        Returns: {QueryId, QueryResult (with all ResultRows merged), HasRemainingRows: False,
                  Batches, TotalRows}
        """
        query_payload = dict(query)
        if int(query_payload.get('CaseDefinitionNo') or 0) == 0:
            query_payload.pop('CaseDefinitionNo', None)
        query_payload['MaxRows'] = int(max_rows)
        query_payload['RowBlockSize'] = int(row_block_size)
        query_id: Optional[int] = None
        batches = 0
        release_error: Optional[str] = None
        result_payload: Dict[str, Any] = {}
        try:
            first = self.execute_async_single_query(query_payload, full_text=full_text)
            query_id = first.get('QueryId') or first.get('QueryID')  # handles both casings
            batches += 1
            has_remaining = bool(first.get('HasRemainingRows'))
            result = first.get('QueryResult') or {}
            rows = list(result.get('ResultRows') or [])
            columns = result.get('Columns')
            while has_remaining and query_id is not None:
                next_resp = self.get_next_single_query_rows(int(query_id), int(row_block_size))
                batches += 1
                has_remaining = bool(next_resp.get('HasRemainingRows'))
                next_result = next_resp.get('QueryResult') or {}
                rows.extend(next_result.get('ResultRows') or [])
                if columns is None and next_result.get('Columns'):
                    columns = next_result.get('Columns')
            merged_result = dict(result)
            merged_result['ResultRows'] = rows
            if columns is not None:
                merged_result['Columns'] = columns
            result_payload = {
                'QueryId': query_id,
                'QueryResult': merged_result,
                'HasRemainingRows': False,
                'Batches': batches,
                'TotalRows': len(rows),
            }
        finally:
            if query_id is not None:
                try:
                    self.release_single_query(int(query_id))
                except Exception as exc:
                    release_error = str(exc)
            if release_error:
                result_payload['ReleaseError'] = release_error
        return result_payload

    def execute_full_text_query(self, search: str, categories: Optional[List[int]] = None, max_rows: int = 100, include_index_data: bool = False, case_no: int = 0) -> Dict[str, Any]:
        payload = {
            'FullTextQuery': {
                'Search': search,
                'Categories': categories or [],
                'MaxRows': max_rows,
                'BlockSize': max_rows,
                'CaseNo': case_no,
                'ContextMaxSizeKB': 0,
                'ContextMode': 0,
                'FuzzySearchLevel': 0,
                'LCID': 0,
                'MaxContentChars': 0,
                'SearchScope': 0,
                'SortOrder': 0,
                'UseThesaurus': False,
            },
            'IncludeIndexData': include_index_data,
        }
        return self._post('ExecuteFullTextQuery', payload)

    def get_document_stream(
        self,
        doc_no: int,
        stream_no: int = 0,
        version_no: int = 0,
        retrieve_reason: str = '',
    ) -> bytes:
        """Download a stream through the POST operation and return its raw bytes."""
        result = self._post('GetDocumentStream', {
            'DocNo': int(doc_no),
            'StreamNo': int(stream_no),
            'VersionNo': int(version_no),
            'RetrieveReason': retrieve_reason,
        })
        file_data = result.get('FileData')
        if file_data is not None:
            return bytes(file_data)
        encoded = result.get('FileDataBase64JSON')
        return base64.b64decode(encoded) if encoded else b''

    def call_endpoint(
        self,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        http_method: str = 'POST',
    ) -> Dict[str, Any]:
        """Call an arbitrary endpoint; POST is the safe default for named operations."""
        if not endpoint:
            raise ValueError('endpoint is required')
        path = str(endpoint).strip()
        if path.startswith(self.base_url):
            path = path[len(self.base_url):]
        path = path.lstrip('/')
        method = http_method.upper()
        if method == 'GET':
            if payload:
                path = f"{path}?{urllib.parse.urlencode(payload, doseq=True)}"
            return self._get(path)
        if method == 'POST':
            return self._post(path, payload or {})
        raise ValueError("http_method must be 'POST' or 'GET'")

    def execute_statistics_query(self, query_type: int, restrict_to_obj_no: Optional[int] = None, restrict_to_user: Optional[bool] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'QueryType': int(query_type)}
        if restrict_to_obj_no is not None:
            payload['RestrictToObjNo'] = int(restrict_to_obj_no)
        if restrict_to_user is not None:
            payload['RestrictToUser'] = bool(restrict_to_user)
        return self._post('ExecuteStatisticsQuery', payload)

    def execute_async_multi_query(self, queries: List[Dict[str, Any]], full_text: Optional[str] = None) -> Dict[str, Any]:
        payload = {'Queries': queries}
        if full_text is not None:
            payload['FullText'] = full_text
        return self._post('ExecuteAsyncMultiQuery', payload)

    def get_next_multi_query_rows(self, query_id: int, row_block_size: int) -> Dict[str, Any]:
        return self._post('GetNextMultiQueryRows', {'QueryID': query_id, 'RowBlockSize': row_block_size})

    def release_multi_query(self, query_id: int) -> Dict[str, Any]:
        return self._post('ReleaseMultiQuery', {'QueryID': query_id})

    def execute_async_multi_query_all(self, queries: List[Dict[str, Any]], full_text: Optional[str] = None, row_block_size: int = 1000, max_rows: int = 2147483647) -> Dict[str, Any]:
        """Execute multiple category queries, preserving each QueryResult wrapper."""
        queries_payload = []
        for q in queries:
            qp = dict(q)
            if int(qp.get('CaseDefinitionNo') or 0) == 0:
                qp.pop('CaseDefinitionNo', None)
            qp['MaxRows'] = int(max_rows)
            qp['RowBlockSize'] = int(row_block_size)
            queries_payload.append(qp)
        query_id: Optional[int] = None
        batches = 0
        release_error: Optional[str] = None
        result_payload: Dict[str, Any] = {}
        try:
            first = self.execute_async_multi_query(queries_payload, full_text=full_text)
            query_id = first.get('QueryId') or first.get('QueryID')
            batches += 1
            has_remaining = bool(first.get('HasRemainingRows'))
            results = list(first.get('QueryResults') or [])

            def query_result_of(item: Dict[str, Any]) -> Dict[str, Any]:
                nested = item.get('QueryResult')
                return nested if isinstance(nested, dict) else item

            def group_key(item: Dict[str, Any]):
                result = query_result_of(item)
                return (
                    result.get('CaseDefinitionNo'),
                    result.get('CategoryNo'),
                    result.get('ProcessNo'),
                )

            def with_rows(item: Dict[str, Any]) -> Dict[str, Any]:
                result = dict(query_result_of(item))
                result['ResultRows'] = list(result.get('ResultRows') or [])
                if isinstance(item.get('QueryResult'), dict):
                    wrapped = dict(item)
                    wrapped['QueryResult'] = result
                    return wrapped
                return result

            merged_map: Dict = {group_key(item): with_rows(item) for item in results}
            while has_remaining and query_id is not None:
                next_resp = self.get_next_multi_query_rows(int(query_id), int(row_block_size))
                batches += 1
                has_remaining = bool(next_resp.get('HasRemainingRows'))
                for item in (next_resp.get('QueryResults') or []):
                    key = group_key(item)
                    if key not in merged_map:
                        merged_map[key] = with_rows(item)
                    else:
                        existing_result = query_result_of(merged_map[key])
                        next_result = query_result_of(item)
                        existing_result['ResultRows'].extend(next_result.get('ResultRows') or [])
            merged_results = list(merged_map.values())
            result_payload = {
                'QueryId': query_id,
                'QueryResults': merged_results,
                'HasRemainingRows': False,
                'Batches': batches,
                'TotalRows': [
                    len(query_result_of(item).get('ResultRows') or [])
                    for item in merged_results
                ],
            }
        finally:
            if query_id is not None:
                try:
                    self.release_multi_query(int(query_id))
                except Exception as exc:
                    release_error = str(exc)
            if release_error:
                result_payload['ReleaseError'] = release_error
        return result_payload

    def update_document_index_data(
        self,
        doc_no: int,
        index_data_items: List[Dict[str, Any]],
        check_in_comments: str = '',
        do_fill_dependent_fields: bool = True,
        last_change_time: Optional[str] = None,
        last_change_time_iso: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update index data using UpdateDocument2.
        IMPORTANT: Requires LastChangeTime or LastChangeTimeISO8601.
        If not provided, fetches current value automatically via GetDocumentIndexData.
        """
        if not last_change_time and not last_change_time_iso:
            current = self.get_document_index_data(doc_no)
            idx = current.get('IndexData') or {}
            last_change_time = idx.get('LastChangeTime')
            last_change_time_iso = idx.get('LastChangeTimeISO8601')
        if not last_change_time and not last_change_time_iso:
            raise ValueError('LastChangeTime or LastChangeTimeISO8601 is required for UpdateDocument2')
        index_data_payload: Dict[str, Any] = {
            'IndexDataItems': index_data_items,
            'DoFillDependentFields': do_fill_dependent_fields,
        }
        if last_change_time:
            index_data_payload['LastChangeTime'] = last_change_time
        if last_change_time_iso:
            index_data_payload['LastChangeTimeISO8601'] = last_change_time_iso
        return self._post('UpdateDocument2', {
            'DocNo': doc_no,
            'IndexData': index_data_payload,
            'CheckInComments': check_in_comments,
        })

    def save_document_index_data(
        self,
        doc_no: int,
        index_data_items: List[Dict[str, Any]],
        check_in_comments: str = '',
        do_fill_dependent_fields: bool = True,
        last_change_time: Optional[str] = None,
        last_change_time_iso: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save index data using SaveDocumentIndexData.
        Requires LastChangeTime (fetched automatically if not provided).
        """
        if not last_change_time and not last_change_time_iso:
            current = self.get_document_index_data(doc_no)
            idx = current.get('IndexData') or {}
            last_change_time = idx.get('LastChangeTime')
            last_change_time_iso = idx.get('LastChangeTimeISO8601')
        if not last_change_time and not last_change_time_iso:
            raise ValueError('LastChangeTime or LastChangeTimeISO8601 is required for SaveDocumentIndexData')
        index_data_payload: Dict[str, Any] = {
            'IndexDataItems': index_data_items,
            'DoFillDependentFields': do_fill_dependent_fields,
        }
        if last_change_time:
            index_data_payload['LastChangeTime'] = last_change_time
        if last_change_time_iso:
            index_data_payload['LastChangeTimeISO8601'] = last_change_time_iso
        return self._post('SaveDocumentIndexData', {
            'DocNo': doc_no,
            'IndexData': index_data_payload,
            'CheckInComments': check_in_comments,
        })

    def update_document(
        self,
        doc_no: int,
        index_data_items: Optional[List[Dict[str, Any]]] = None,
        streams_to_update: Optional[List[Dict[str, Any]]] = None,
        stream_nos_to_delete: Optional[List[int]] = None,
        streams_to_rename: Optional[List[Dict[str, Any]]] = None,
        conversion_options: Optional[Dict[str, Any]] = None,
        check_in_comments: str = '',
        do_fill_dependent_fields: bool = True,
        last_change_time: Optional[str] = None,
        last_change_time_iso: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update document index data and/or streams. Requires LastChangeTime."""
        if not last_change_time and not last_change_time_iso:
            current = self.get_document_index_data(doc_no)
            idx = current.get('IndexData') or {}
            last_change_time = idx.get('LastChangeTime')
            last_change_time_iso = idx.get('LastChangeTimeISO8601')
        if not last_change_time and not last_change_time_iso:
            raise ValueError('LastChangeTime or LastChangeTimeISO8601 is required for UpdateDocument')
        index_data_payload: Dict[str, Any] = {
            'IndexDataItems': index_data_items or [],
            'DoFillDependentFields': do_fill_dependent_fields,
        }
        if last_change_time:
            index_data_payload['LastChangeTime'] = last_change_time
        if last_change_time_iso:
            index_data_payload['LastChangeTimeISO8601'] = last_change_time_iso
        payload: Dict[str, Any] = {'DocNo': doc_no, 'IndexData': index_data_payload, 'CheckInComments': check_in_comments}
        if streams_to_update:
            payload['StreamsToUpdate'] = streams_to_update
        if stream_nos_to_delete:
            payload['StreamNosToDelete'] = stream_nos_to_delete
        if streams_to_rename:
            payload['StreamsToRename'] = streams_to_rename
        if conversion_options:
            payload['ConversionOptions'] = conversion_options
        return self._post('UpdateDocument', payload)

    def add_streams_to_document(self, doc_no: int, streams: List[Dict[str, Any]], conversion_options: Optional[Dict[str, Any]] = None, check_in_comments: str = '') -> Dict[str, Any]:
        payload: Dict[str, Any] = {'DocNo': doc_no, 'CheckInComments': check_in_comments, 'StreamsToUpload': streams}
        if conversion_options:
            payload['ConversionOptions'] = conversion_options
        return self._post('AddStreamsToDocument', payload)

    def get_converted_doc_streams(self, doc_no: int, conversion_options: Dict[str, Any], stream_nos: Optional[List[int]] = None, version_no: Optional[int] = None, is_file_data_base64_json_needed: Optional[bool] = None, retrieve_reason: Optional[str] = None, archive_converted_files: Optional[bool] = None, custom_archive_file_name: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'DocNo': int(doc_no), 'ConversionOptions': conversion_options}
        if stream_nos is not None:
            payload['StreamNos'] = [int(s) for s in stream_nos]
        if version_no is not None:
            payload['VersionNo'] = int(version_no)
        if is_file_data_base64_json_needed is not None:
            payload['IsFileDataBase64JSONNeeded'] = bool(is_file_data_base64_json_needed)
        if retrieve_reason is not None:
            payload['RetrieveReason'] = retrieve_reason
        if archive_converted_files is not None:
            payload['ArchiveConvertedFiles'] = bool(archive_converted_files)
        if custom_archive_file_name is not None:
            payload['CustomArchiveFileName'] = custom_archive_file_name
        return self._post('GetConvertedDocStreams', payload)

    def get_login_history(self, max_entries: Optional[int] = None, timestamp_from: Optional[str] = None, user_no: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if max_entries is not None:
            payload['MaxEntries'] = int(max_entries)
        if timestamp_from is not None:
            payload['TimestampFrom'] = timestamp_from
        if user_no is not None:
            payload['UserNo'] = int(user_no)
        return self._post('GetLoginHistory', payload)

    @staticmethod
    def make_stream_from_text(filename: str, text: str) -> Dict[str, Any]:
        """Create a stream dict from plain text for use with create_document/update_document."""
        data = base64.b64encode(text.encode('utf-8')).decode('ascii')
        return {
            'FileName': filename,
            'FileDataBase64JSON': data,
            'NewStreamInsertMode': 0,
        }


def load_env(path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
    for k, v in os.environ.items():
        if k.startswith('THEREFORE_'):
            values[k] = v
    return values


def build_config_from_env(env: Dict[str, str]) -> ThereforeConfig:
    def clean(v):
        if v is None:
            return None
        v = v.strip()
        if not v or v.upper().startswith('THIS IS NOT NEEDED'):
            return None
        return v

    workflow_timeout_seconds = None
    workflow_max_rows = None
    workflow_retry_timeout_seconds = None
    workflow_retry_count = 0

    for key, attr, min_val in [
        ('THEREFORE_WORKFLOW_TIMEOUT_SECONDS', 'workflow_timeout_seconds', 1),
        ('THEREFORE_WORKFLOW_MAX_ROWS', 'workflow_max_rows', 1),
        ('THEREFORE_WORKFLOW_RETRY_TIMEOUT_SECONDS', 'workflow_retry_timeout_seconds', 1),
        ('THEREFORE_WORKFLOW_RETRY_COUNT', 'workflow_retry_count', 0),
    ]:
        raw = clean(env.get(key))
        if raw:
            try:
                val = max(min_val, int(raw))
                if key == 'THEREFORE_WORKFLOW_RETRY_COUNT':
                    workflow_retry_count = val
                elif key == 'THEREFORE_WORKFLOW_TIMEOUT_SECONDS':
                    workflow_timeout_seconds = val
                elif key == 'THEREFORE_WORKFLOW_MAX_ROWS':
                    workflow_max_rows = val
                elif key == 'THEREFORE_WORKFLOW_RETRY_TIMEOUT_SECONDS':
                    workflow_retry_timeout_seconds = val
            except ValueError:
                pass

    debug_raw = clean(env.get('THEREFORE_DEBUG'))
    debug = debug_raw is not None and debug_raw.lower() in ('1', 'true', 'yes')

    return ThereforeConfig(
        base_url=clean(env.get('THEREFORE_BASE_URL')) or '',
        auth_method=clean(env.get('THEREFORE_AUTH_METHOD')) or 'Basic',
        username=clean(env.get('THEREFORE_USERNAME')),
        password=clean(env.get('THEREFORE_PASSWORD')),
        tenant_name=clean(env.get('THEREFORE_TENANTNAME')),
        timeout_seconds=20,
        workflow_timeout_seconds=workflow_timeout_seconds,
        workflow_max_rows=workflow_max_rows,
        workflow_retry_timeout_seconds=workflow_retry_timeout_seconds,
        workflow_retry_count=workflow_retry_count,
        debug=debug,
    )


def normalize_tenant_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(name).lower())


def build_tenant_configs_from_env(env: Dict[str, str]):
    tenants_raw = (env.get('THEREFORE_TENANTS') or '').strip()
    if not tenants_raw:
        cfg = build_config_from_env(env)
        return {'default': cfg}, 'default', {'default': 'default'}

    tenants = [t.strip() for t in tenants_raw.split(',') if t.strip()]
    if not tenants:
        cfg = build_config_from_env(env)
        return {'default': cfg}, 'default', {'default': 'default'}

    default_name = (env.get('THEREFORE_DEFAULT_TENANT') or tenants[0]).strip()
    default_key = normalize_tenant_key(default_name)

    configs = {}
    display_names = {}
    for name in tenants:
        key = normalize_tenant_key(name)
        if not key:
            continue
        prefix = f"THEREFORE_{name.upper()}_"
        def pick(suffix):
            return env.get(prefix + suffix) or env.get('THEREFORE_' + suffix)
        tenant_env = {k: v for k, v in {
            'THEREFORE_BASE_URL': pick('BASE_URL'),
            'THEREFORE_AUTH_METHOD': pick('AUTH_METHOD'),
            'THEREFORE_USERNAME': pick('USERNAME'),
            'THEREFORE_PASSWORD': pick('PASSWORD'),
            'THEREFORE_TENANTNAME': pick('TENANTNAME'),
            'THEREFORE_WORKFLOW_TIMEOUT_SECONDS': env.get('THEREFORE_WORKFLOW_TIMEOUT_SECONDS'),
            'THEREFORE_WORKFLOW_MAX_ROWS': env.get('THEREFORE_WORKFLOW_MAX_ROWS'),
        }.items() if v is not None}
        configs[key] = build_config_from_env(tenant_env)
        display_names[key] = name

    if default_key not in configs and configs:
        default_key = next(iter(configs.keys()))
    return configs, default_key, display_names
