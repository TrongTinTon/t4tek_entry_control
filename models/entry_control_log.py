from odoo import models, fields

class EntryControlLog(models.Model):
    _name = 'entry.control.log'
    _description = 'Entry Control Raw Log'
    _order = 'event_time desc'

    name = fields.Char(string='Event ID', required=True, readonly=True)
    controller_id = fields.Char(string='Controller ID', readonly=True)
    controller_ref_id = fields.Many2one('entry.control.controller', string='Controller', readonly=True, ondelete='set null')
    device_ip = fields.Char(string='Device IP', readonly=True)
    device_user_id = fields.Char(string='User ID', readonly=True)
    entry_user_id = fields.Many2one('entry.control.user', string='Device User', readonly=True, ondelete='set null')
    employee_id = fields.Many2one('hr.employee', string='Nhân viên', readonly=True)
    event_time = fields.Datetime(string='Thời gian sự kiện', readonly=True)
    captured_at = fields.Datetime(string='Captured At', readonly=True, default=fields.Datetime.now)
    
    action = fields.Selection([
        ('check_in', 'Vào công ty'),
        ('check_out', 'Ra công ty'),
        ('invalid_access', 'Truy cập không hợp lệ')
    ], string='Hành động', readonly=True)
    
    status = fields.Selection([
        ('success', 'đã quét'), 
        ('error', 'Lỗi')
    ], string='Trạng thái', readonly=True)
    error_message = fields.Char(string='Thông báo lỗi', readonly=True)
    raw_payload = fields.Text(string='Dữ liệu gốc (JSON)', readonly=True)

class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    entry_control_log_ids = fields.One2many(
        comodel_name='entry.control.log', 
        inverse_name='employee_id', 
        string='Lịch sử Vào/Ra (Entry Control)'
    )