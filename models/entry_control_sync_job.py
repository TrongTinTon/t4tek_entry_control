import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EntryControlSyncJob(models.Model):
    _name = 'entry.control.sync.job'
    _description = 'Attendance Gateway Sync Job'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Job Name', required=True, default='Sync Job')
    job_uid = fields.Char(string='Job ID', required=True, readonly=True, copy=False, index=True)
    job_type = fields.Selection([
        ('user_sync', 'User Sync'),
        ('fingerprint_pull', 'Fingerprint Pull'),
        ('fingerprint_push', 'Fingerprint Push'),
        ('face_pull', 'Face Pull'),
        ('face_push', 'Face Push'),
        ('attendance_repush', 'Attendance Re-push'),
        ('device_diagnostic', 'Device Diagnostic'),
    ], string='Job Type', required=True, default='user_sync', index=True)

    device_id = fields.Many2one('entry.control.device', string='Device', required=True, ondelete='cascade', index=True)
    controller_id = fields.Many2one('entry.control.controller', string='Controller', related='device_id.controller_id', store=True, readonly=True)

    state = fields.Selection([
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('completed', 'Completed'),
        ('partial_success', 'Partial Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='queued', index=True)

    progress_percent = fields.Integer(string='Progress', default=0)
    batch_size = fields.Integer(string='Batch Size', default=0)
    total_items = fields.Integer(string='Total Items')
    processed_items = fields.Integer(string='Processed Items')
    success_count = fields.Integer(string='Success')
    failed_count = fields.Integer(string='Failed')
    skipped_count = fields.Integer(string='Skipped')

    # User sync counters
    requested_count = fields.Integer(string='Requested Users')
    created_or_updated_count = fields.Integer(string='Upserted Users')
    deleted_count = fields.Integer(string='Deleted Users')
    preserved_count = fields.Integer(string='Preserved Users')
    device_user_count_before = fields.Integer(string='Device Users Before')
    device_user_count_after = fields.Integer(string='Device Users After')

    # Fingerprint counters
    total_templates = fields.Integer(string='Total Templates')
    sent_templates = fields.Integer(string='Sent Templates')
    imported_templates = fields.Integer(string='Imported Templates')
    updated_templates = fields.Integer(string='Updated Templates')
    skipped_templates = fields.Integer(string='Skipped Templates')
    failed_users = fields.Integer(string='Failed Users')
    last_batch_no = fields.Integer(string='Last Batch No')

    current_pin = fields.Char(string='Current PIN')
    current_step = fields.Char(string='Current Step')
    message = fields.Text(string='Message')
    last_error = fields.Text(string='Last Error')

    legacy_model = fields.Char(string='Legacy Model', readonly=True, copy=False)
    legacy_res_id = fields.Integer(string='Legacy Record ID', readonly=True, copy=False)
    request_payload = fields.Text(string='Request Payload', readonly=True, copy=False)
    result_payload = fields.Text(string='Result Payload', readonly=True, copy=False)

    started_at = fields.Datetime(string='Started At')
    finished_at = fields.Datetime(string='Finished At')
    last_update_at = fields.Datetime(string='Last Update At')

    line_ids = fields.One2many('entry.control.sync.line', 'job_id', string='Lines')
    line_count = fields.Integer(string='Lines', compute='_compute_line_count')

    _sql_constraints = [
        ('job_uid_unique', 'unique(job_uid)', 'Sync Job ID must be unique.'),
    ]

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def _notification_action(self, title, message, notification_type='success', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': sticky,
            },
        }

    def _normalize_state(self, state):
        state = (state or '').strip().lower()
        if state in ('ok', 'done'):
            return 'success'
        if state in ('complete', 'completed'):
            return 'completed'
        if state in ('partial', 'partial_success'):
            return 'partial_success'
        if state in ('running_with_errors', 'in_progress'):
            return 'running'
        if state in ('success', 'queued', 'running', 'failed', 'cancelled'):
            return state
        return 'running'

    def _int_from(self, data, keys, default=0):
        for key in keys:
            if key in data and data.get(key) not in (None, ''):
                try:
                    return int(data.get(key) or 0)
                except Exception:
                    return default
        return default

    def _has(self, data, *keys):
        return any(key in data for key in keys)

    def _apply_controller_payload(self, data, job_type=None):
        self.ensure_one()
        data = data or {}
        state = self._normalize_state(data.get('state') or self.state)
        progress = self._int_from(data, ('progressPercent', 'progress_percent'), self.progress_percent or 0)
        progress = max(0, min(100, progress))
        if state in ('success', 'completed', 'partial_success'):
            progress = 100

        vals = {
            'state': state,
            'progress_percent': progress,
            'current_pin': data.get('currentPin') or data.get('current_pin') or self.current_pin or '',
            'current_step': data.get('currentStep') or data.get('current_step') or self.current_step or '',
            'message': data.get('message') or self.message or '',
            'last_update_at': fields.Datetime.now(),
            'result_payload': json.dumps(data, ensure_ascii=False, indent=2),
        }

        if job_type:
            vals['job_type'] = job_type

        if state == 'running' and not self.started_at:
            vals['started_at'] = fields.Datetime.now()
        if state in ('success', 'completed', 'partial_success', 'failed', 'cancelled'):
            vals['finished_at'] = fields.Datetime.now()
        if state == 'failed':
            vals['last_error'] = data.get('lastError') or data.get('error') or vals['message']

        if self.job_type == 'user_sync' or job_type == 'user_sync':
            mapping = {
                'requested_count': ('requestedCount', 'requested_count'),
                'created_or_updated_count': ('createdOrUpdatedCount', 'created_or_updated_count'),
                'deleted_count': ('deletedCount', 'deleted_count'),
                'preserved_count': ('preservedCount', 'preserved_count'),
                'failed_count': ('failedCount', 'failed_count'),
                'device_user_count_before': ('deviceUserCountBefore', 'device_user_count_before'),
                'device_user_count_after': ('deviceUserCountAfter', 'device_user_count_after'),
                'total_items': ('totalCount', 'total_count', 'requestedCount'),
                'processed_items': ('processedCount', 'processed_count'),
            }
            for field_name, keys in mapping.items():
                if self._has(data, *keys):
                    vals[field_name] = self._int_from(data, keys, 0)
            vals['success_count'] = vals.get('created_or_updated_count', self.created_or_updated_count or 0)
            self.write(vals)
            self._upsert_user_sync_lines(data)
            return True

        if self.job_type == 'fingerprint_pull' or job_type == 'fingerprint_pull':
            mapping = {
                'batch_size': ('batchSize', 'batch_size'),
                'total_items': ('totalUsers', 'total_users'),
                'processed_items': ('processedUsers', 'processed_users'),
                'total_templates': ('totalTemplates', 'total_templates'),
                'sent_templates': ('sentTemplates', 'sent_templates'),
                'imported_templates': ('importedTemplates', 'imported_templates'),
                'updated_templates': ('updatedTemplates', 'updated_templates'),
                'skipped_templates': ('skippedTemplates', 'skipped_templates'),
                'failed_users': ('failedUsers', 'failed_users'),
                'last_batch_no': ('batchNo', 'batch_no', 'lastBatchNo', 'last_batch_no'),
            }
            for field_name, keys in mapping.items():
                if self._has(data, *keys):
                    vals[field_name] = self._int_from(data, keys, 0)
            vals['success_count'] = (vals.get('imported_templates', self.imported_templates or 0) or 0) + (vals.get('updated_templates', self.updated_templates or 0) or 0)
            vals['skipped_count'] = vals.get('skipped_templates', self.skipped_templates or 0) or 0
            vals['failed_count'] = vals.get('failed_users', self.failed_users or 0) or 0
            self.write(vals)
            return True

        if self.job_type == 'fingerprint_push' or job_type == 'fingerprint_push':
            mapping = {
                'requested_count': ('requestedCount', 'requested_count'),
                'total_items': ('totalCount', 'total_count', 'requestedCount'),
                'processed_items': ('processedCount', 'processed_count'),
                'total_templates': ('totalCount', 'total_count', 'requestedCount'),
                'sent_templates': ('uploadedCount', 'uploaded_count'),
                'failed_count': ('failedCount', 'failed_count'),
            }
            for field_name, keys in mapping.items():
                if self._has(data, *keys):
                    vals[field_name] = self._int_from(data, keys, 0)
            vals['success_count'] = vals.get('sent_templates', self.sent_templates or 0) or 0
            self.write(vals)
            self._upsert_fingerprint_push_lines(data)
            return True

        self.write(vals)
        return True

    def _upsert_user_sync_lines(self, data):
        self.ensure_one()
        Line = self.env['entry.control.sync.line'].sudo()

        def upsert(pin, state, message, item_type='user', item_key=None):
            pin = str(pin or '').strip()
            if not pin:
                return
            item_key = item_key or ('%s:%s' % (item_type, pin))
            line = Line.search([('job_id', '=', self.id), ('item_key', '=', item_key)], limit=1)
            vals = {
                'job_id': self.id,
                'device_id': self.device_id.id,
                'pin': pin,
                'item_type': item_type,
                'item_key': item_key,
                'state': state,
                'message': message,
                'finished_at': fields.Datetime.now(),
            }
            if line:
                line.write(vals)
            else:
                Line.create(vals)

        for pin in data.get('syncedPins') or []:
            upsert(pin, 'success', 'User created/updated on device.')
        for pin in data.get('deletedPins') or []:
            upsert(pin, 'deleted', 'User deleted from device.', item_key='deleted:%s' % pin)
        for pin in data.get('preservedPins') or []:
            upsert(pin, 'skipped', 'User preserved on device.', item_key='preserved:%s' % pin)
        for pin in data.get('failedPins') or []:
            upsert(pin, 'failed', 'User sync failed.', item_key='failed:%s' % pin)


    def _upsert_fingerprint_push_lines(self, data):
        self.ensure_one()
        results = data.get('results') or []
        if not isinstance(results, list):
            return
        Line = self.env['entry.control.sync.line'].sudo()
        Biometric = self.env['entry.control.biometric'].sudo()

        for item in results:
            if not isinstance(item, dict):
                continue
            pin = str(item.get('pin') or '').strip()
            try:
                finger_index = int(item.get('fingerIndex') or 0)
            except Exception:
                finger_index = 0
            if not pin:
                continue
            success = bool(item.get('success'))
            item_key = 'fingerprint:%s:%s' % (pin, finger_index)
            biometric = Biometric.search([
                ('user_id.pin', '=', pin),
                ('user_id.controller_id', '=', self.controller_id.id),
                ('biometric_type', '=', 'fingerprint'),
                ('finger_index', '=', finger_index),
            ], limit=1)
            line = Line.search([('job_id', '=', self.id), ('item_key', '=', item_key)], limit=1)
            vals = {
                'job_id': self.id,
                'device_id': self.device_id.id,
                'pin': pin,
                'user_id': biometric.user_id.id if biometric else False,
                'item_type': 'fingerprint',
                'item_key': item_key,
                'finger_index': finger_index,
                'state': 'success' if success else 'failed',
                'message': item.get('message') or ('Fingerprint push OK.' if success else 'Fingerprint push failed.'),
                'template_length': int(item.get('templateLength') or 0),
                'biometric_id': biometric.id if biometric else False,
                'raw_item': json.dumps(item, ensure_ascii=False, indent=2),
                'finished_at': fields.Datetime.now(),
            }
            if line:
                line.write(vals)
            else:
                Line.create(vals)

    def action_refresh_progress(self):
        messages = []
        notification_type = 'success'
        for rec in self:
            if rec.job_type == 'user_sync':
                data = rec.device_id._call_agent_full_sync_status(job_id=rec.job_uid, raise_error=False)
            elif rec.job_type == 'fingerprint_pull':
                data = rec.device_id._call_agent_fingerprint_pull_status(job_id=rec.job_uid, raise_error=False)
            elif rec.job_type == 'fingerprint_push':
                data = rec.device_id._call_agent_fingerprint_push_status(job_id=rec.job_uid, raise_error=False)
            else:
                data = False
            if isinstance(data, dict):
                rec._apply_controller_payload(data)
            if rec.state in ('failed', 'partial_success'):
                notification_type = 'warning'
            messages.append('%s: %s%% %s' % (rec.display_name, rec.progress_percent or 0, rec.current_step or rec.state))
        return self._notification_action('Refresh Sync Job', '; '.join(messages[:5]), notification_type=notification_type)

    def action_retry_resume(self):
        messages = []
        for rec in self:
            if rec.job_type == 'fingerprint_pull':
                rec.device_id._call_agent_fingerprint_pull_retry(job_id=rec.job_uid, raise_error=True)
                messages.append('%s: retry/resume requested.' % rec.display_name)
            else:
                raise UserError('Retry/resume is currently implemented for Fingerprint Pull jobs only. Start a new Sync All Users job for user_sync.')
        return self._notification_action('Retry / Resume Sync Job', '; '.join(messages[:5]), notification_type='warning')

    def action_view_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sync Job Lines',
            'res_model': 'entry.control.sync.line',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }


class EntryControlSyncLine(models.Model):
    _name = 'entry.control.sync.line'
    _description = 'Attendance Gateway Sync Job Line'
    _order = 'job_id desc, batch_no, pin, id'

    job_id = fields.Many2one('entry.control.sync.job', string='Job', required=True, ondelete='cascade', index=True)
    device_id = fields.Many2one('entry.control.device', string='Device', required=True, ondelete='cascade', index=True)
    batch_no = fields.Integer(string='Batch No')
    pin = fields.Char(string='PIN', index=True)
    user_id = fields.Many2one('entry.control.user', string='Device User')
    item_type = fields.Selection([
        ('user', 'User'),
        ('fingerprint', 'Fingerprint'),
        ('face', 'Face'),
        ('attendance', 'Attendance'),
        ('device', 'Device'),
    ], string='Item Type', default='user', index=True)
    item_key = fields.Char(string='Item Key', index=True)
    finger_index = fields.Integer(string='Finger Index')
    state = fields.Selection([
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('imported', 'Imported'),
        ('updated', 'Updated'),
        ('deleted', 'Deleted'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ], string='State', default='queued', index=True)
    message = fields.Text(string='Message')
    template_length = fields.Integer(string='Template Length')
    template_hash = fields.Char(string='Template Hash', index=True)
    biometric_id = fields.Many2one('entry.control.biometric', string='Biometric Template')
    raw_item = fields.Text(string='Raw Item')
    started_at = fields.Datetime(string='Started At')
    finished_at = fields.Datetime(string='Finished At')
