import hashlib
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EntryControlBiometricPullJob(models.Model):
    _name = 'entry.control.biometric.pull.job'
    _description = 'Fingerprint Pull Job'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Job Name', required=True, default='Fingerprint Pull Job')
    job_id = fields.Char(string='Job ID', required=True, readonly=True, copy=False, index=True)
    device_id = fields.Many2one('entry.control.device', string='Device', required=True, ondelete='cascade')
    controller_id = fields.Many2one('entry.control.controller', string='Controller', related='device_id.controller_id', store=True, readonly=True)

    state = fields.Selection([
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('partial_success', 'Partial Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='queued', index=True)

    progress_percent = fields.Integer(string='Progress', default=0)
    batch_size = fields.Integer(string='Batch Size', default=50)
    total_users = fields.Integer(string='Total Users')
    processed_users = fields.Integer(string='Processed Users')
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

    started_at = fields.Datetime(string='Started At')
    finished_at = fields.Datetime(string='Finished At')
    last_update_at = fields.Datetime(string='Last Update At')

    line_ids = fields.One2many('entry.control.biometric.pull.line', 'job_id', string='Lines')
    line_count = fields.Integer(string='Lines', compute='_compute_line_count')

    _sql_constraints = [
        ('job_id_unique', 'unique(job_id)', 'Fingerprint pull Job ID must be unique.'),
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

    def action_refresh_progress(self):
        messages = []
        for rec in self:
            data = rec.device_id._call_agent_fingerprint_pull_status(job_id=rec.job_id, raise_error=True)
            messages.append('%s: %s%% %s' % (rec.display_name, rec.progress_percent or 0, rec.current_step or rec.state))
        return self._notification_action('Refresh Fingerprint Pull Progress', '; '.join(messages[:5]))

    def action_retry_resume(self):
        messages = []
        for rec in self:
            rec.device_id._call_agent_fingerprint_pull_retry(job_id=rec.job_id, raise_error=True)
            messages.append('%s: retry/resume requested.' % rec.display_name)
        return self._notification_action('Retry Fingerprint Pull', '; '.join(messages[:5]))

    def action_view_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fingerprint Pull Lines',
            'res_model': 'entry.control.biometric.pull.line',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }

    def _apply_progress_payload(self, data):
        self.ensure_one()
        state = data.get('state') or self.state or 'running'
        progress = int(data.get('progressPercent') or data.get('progress_percent') or self.progress_percent or 0)
        progress = max(0, min(100, progress))
        vals = {
            'state': state,
            'progress_percent': progress,
            'total_users': int(data.get('totalUsers') or data.get('total_users') or self.total_users or 0),
            'processed_users': int(data.get('processedUsers') or data.get('processed_users') or self.processed_users or 0),
            'total_templates': int(data.get('totalTemplates') or data.get('total_templates') or self.total_templates or 0),
            'sent_templates': int(data.get('sentTemplates') or data.get('sent_templates') or self.sent_templates or 0),
            'imported_templates': int(data.get('importedTemplates') or data.get('imported_templates') or self.imported_templates or 0),
            'updated_templates': int(data.get('updatedTemplates') or data.get('updated_templates') or self.updated_templates or 0),
            'skipped_templates': int(data.get('skippedTemplates') or data.get('skipped_templates') or self.skipped_templates or 0),
            'failed_users': int(data.get('failedUsers') or data.get('failed_users') or self.failed_users or 0),
            'current_pin': data.get('currentPin') or data.get('current_pin') or '',
            'current_step': data.get('currentStep') or data.get('current_step') or '',
            'message': data.get('message') or self.message or '',
            'last_update_at': fields.Datetime.now(),
        }
        if state == 'running' and not self.started_at:
            vals['started_at'] = fields.Datetime.now()
        if state in ('completed', 'partial_success', 'failed', 'cancelled'):
            vals['finished_at'] = fields.Datetime.now()
            if state in ('completed', 'partial_success'):
                vals['progress_percent'] = 100
        if state == 'failed':
            vals['last_error'] = data.get('lastError') or data.get('error') or vals['message']
        self.write(vals)
        try:
            self._get_or_create_sync_job()._apply_controller_payload(data, job_type='fingerprint_pull')
        except Exception:
            _logger.exception('[ENTRY CONTROL] Failed to mirror fingerprint pull progress to generic Sync Job.')


    def _get_or_create_sync_job(self):
        self.ensure_one()
        SyncJob = self.env['entry.control.sync.job'].sudo()
        job = SyncJob.search([('job_uid', '=', self.job_id)], limit=1)
        if job:
            return job
        return SyncJob.create({
            'name': self.name or 'Fingerprint Pull Job',
            'job_uid': self.job_id,
            'job_type': 'fingerprint_pull',
            'device_id': self.device_id.id,
            'state': self.state or 'queued',
            'progress_percent': self.progress_percent or 0,
            'batch_size': self.batch_size or 50,
            'legacy_model': self._name,
            'legacy_res_id': self.id,
            'current_step': self.current_step or '',
            'current_pin': self.current_pin or '',
            'message': self.message or '',
        })

    def _mirror_lines_to_sync_job(self, batch_no=None):
        self.ensure_one()
        sync_job = self._get_or_create_sync_job()
        SyncLine = self.env['entry.control.sync.line'].sudo()
        domain = [('job_id', '=', self.id)]
        if batch_no:
            domain.append(('batch_no', '=', batch_no))
        for line in self.env['entry.control.biometric.pull.line'].sudo().search(domain):
            item_key = 'fingerprint:%s:%s' % (line.pin or '', line.finger_index or 0)
            existing = SyncLine.search([('job_id', '=', sync_job.id), ('item_key', '=', item_key)], limit=1)
            vals = {
                'job_id': sync_job.id,
                'device_id': self.device_id.id,
                'batch_no': line.batch_no or 0,
                'pin': line.pin or '',
                'user_id': line.user_id.id,
                'item_type': 'fingerprint',
                'item_key': item_key,
                'finger_index': line.finger_index or 0,
                'state': line.state,
                'message': line.message or '',
                'template_length': line.template_length or 0,
                'template_hash': line.template_hash or '',
                'biometric_id': line.biometric_id.id,
                'raw_item': line.raw_item or '',
                'finished_at': fields.Datetime.now(),
            }
            if existing:
                existing.write(vals)
            else:
                SyncLine.create(vals)
        return sync_job

    def _import_batch_payload(self, data):
        self.ensure_one()
        device = self.device_id
        templates = data.get('templates') or []
        batch_no = int(data.get('batchNo') or data.get('batch_no') or 0)
        imported = 0
        updated = 0
        skipped = 0
        failed = 0
        messages = []

        for item in templates:
            try:
                status = self._import_template_item(device, item, batch_no=batch_no)
                if status == 'imported':
                    imported += 1
                elif status == 'updated':
                    updated += 1
                else:
                    skipped += 1
            except Exception as ex:
                failed += 1
                pin = str((item or {}).get('pin') or '').strip()
                msg = 'PIN %s: %s' % (pin, str(ex))
                messages.append(msg)
                self.env['entry.control.biometric.pull.line'].sudo().create({
                    'job_id': self.id,
                    'device_id': device.id,
                    'pin': pin,
                    'state': 'failed',
                    'message': msg,
                    'raw_item': json.dumps(item or {}, ensure_ascii=False),
                })

        vals = {
            'last_batch_no': max(self.last_batch_no or 0, batch_no),
            'imported_templates': (self.imported_templates or 0) + imported,
            'updated_templates': (self.updated_templates or 0) + updated,
            'skipped_templates': (self.skipped_templates or 0) + skipped,
            'failed_users': (self.failed_users or 0) + failed,
            'last_update_at': fields.Datetime.now(),
        }
        progress_data = dict(data)
        progress_data['importedTemplates'] = vals['imported_templates']
        progress_data['updatedTemplates'] = vals['updated_templates']
        progress_data['skippedTemplates'] = vals['skipped_templates']
        progress_data['failedUsers'] = vals['failed_users']
        self.write(vals)
        self._apply_progress_payload(progress_data)
        try:
            self._mirror_lines_to_sync_job(batch_no=batch_no)
        except Exception:
            _logger.exception('[ENTRY CONTROL] Failed to mirror fingerprint pull lines to generic Sync Job.')
        return {
            'imported': imported,
            'updated': updated,
            'skipped': skipped,
            'failed': failed,
            'messages': messages[:10],
        }

    def _import_template_item(self, device, item, batch_no=0):
        Biometric = self.env['entry.control.biometric'].sudo()
        Line = self.env['entry.control.biometric.pull.line'].sudo()

        pin = str(item.get('pin') or '').strip()
        if not pin:
            Line.create({
                'job_id': self.id,
                'device_id': device.id,
                'batch_no': batch_no,
                'state': 'skipped',
                'message': 'Skipped template without PIN.',
                'raw_item': json.dumps(item or {}, ensure_ascii=False),
            })
            return 'skipped'

        device_user = device._find_device_user_by_pin(pin)
        if not device_user:
            Line.create({
                'job_id': self.id,
                'device_id': device.id,
                'batch_no': batch_no,
                'pin': pin,
                'state': 'skipped',
                'message': 'No Device User mapped on Odoo.',
                'raw_item': json.dumps(item or {}, ensure_ascii=False),
            })
            return 'skipped'

        try:
            finger_index = int(item.get('fingerIndex') if item.get('fingerIndex') is not None else item.get('finger_index'))
        except Exception:
            finger_index = 0
        if finger_index < 0 or finger_index > 9:
            Line.create({
                'job_id': self.id,
                'device_id': device.id,
                'batch_no': batch_no,
                'pin': pin,
                'finger_index': finger_index,
                'state': 'skipped',
                'message': 'Finger index must be 0-9.',
                'raw_item': json.dumps(item or {}, ensure_ascii=False),
            })
            return 'skipped'

        template_data = item.get('templateData') or item.get('template_data') or ''
        if not template_data:
            Line.create({
                'job_id': self.id,
                'device_id': device.id,
                'batch_no': batch_no,
                'pin': pin,
                'finger_index': finger_index,
                'state': 'skipped',
                'message': 'Empty template data.',
                'raw_item': json.dumps(item or {}, ensure_ascii=False),
            })
            return 'skipped'

        template_hash = hashlib.sha256(template_data.encode('utf-8')).hexdigest()
        biometric = Biometric.search([
            ('user_id', '=', device_user.id),
            ('biometric_type', '=', 'fingerprint'),
            ('finger_index', '=', finger_index),
        ], limit=1)

        template_length = int(item.get('templateLength') or item.get('template_length') or len(template_data))
        vals = {
            'user_id': device_user.id,
            'biometric_type': 'fingerprint',
            'finger_index': finger_index,
            'flag': int(item.get('flag') or 1),
            'template_data': template_data,
            'template_hash': template_hash,
            'template_length': template_length,
            'algorithm': device._map_fingerprint_algorithm(item.get('algorithm') or 'ZKFinger10'),
            'source_device_id': device.id,
            'sync_state': 'pulled',
            'last_sync_at': fields.Datetime.now(),
            'last_sync_device_id': device.id,
            'last_sync_message': 'Pulled by fingerprint job %s. DevicePIN=%s OdooPIN=%s FingerIndex=%s Length=%s' % (
                self.job_id, pin, device_user.pin, finger_index, template_length,
            ),
        }

        state = 'imported'
        if biometric:
            if biometric.template_hash == template_hash:
                state = 'skipped'
                message = 'Template unchanged. Hash already exists.'
            else:
                biometric.write(vals)
                state = 'updated'
                message = 'Template updated from batch %s.' % batch_no
        else:
            biometric = Biometric.create(vals)
            message = 'Template imported from batch %s.' % batch_no

        Line.create({
            'job_id': self.id,
            'device_id': device.id,
            'batch_no': batch_no,
            'pin': pin,
            'user_id': device_user.id,
            'finger_index': finger_index,
            'state': state,
            'template_length': template_length,
            'template_hash': template_hash,
            'biometric_id': biometric.id,
            'message': message,
            'raw_item': json.dumps({
                'pin': pin,
                'fingerIndex': finger_index,
                'templateLength': template_length,
                'algorithm': item.get('algorithm') or 'ZKFinger10',
                'method': item.get('method') or '',
            }, ensure_ascii=False),
        })
        return state


class EntryControlBiometricPullLine(models.Model):
    _name = 'entry.control.biometric.pull.line'
    _description = 'Fingerprint Pull Job Line'
    _order = 'job_id desc, batch_no, pin, finger_index, id'

    job_id = fields.Many2one('entry.control.biometric.pull.job', string='Job', required=True, ondelete='cascade', index=True)
    device_id = fields.Many2one('entry.control.device', string='Device', readonly=True)
    batch_no = fields.Integer(string='Batch No')
    pin = fields.Char(string='PIN', index=True)
    user_id = fields.Many2one('entry.control.user', string='Device User')
    finger_index = fields.Integer(string='Finger Index')
    state = fields.Selection([
        ('imported', 'Imported'),
        ('updated', 'Updated'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ], string='State', default='imported', index=True)
    template_length = fields.Integer(string='Template Length')
    template_hash = fields.Char(string='Template Hash', index=True)
    biometric_id = fields.Many2one('entry.control.biometric', string='Biometric Template')
    message = fields.Text(string='Message')
    raw_item = fields.Text(string='Raw Item')
