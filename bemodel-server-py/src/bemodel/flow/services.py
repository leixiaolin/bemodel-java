import json
from sqlalchemy import select
from bemodel.datasource.services import DatasourceService
from bemodel.datasource.entities import Mapping
from bemodel.core.exceptions import BizException
from bemodel.core.page_result import page_result


def string(value):
    return 'null' if value is None else str(value)


class FlowService:
    def __init__(self, session):
        self.session = session
        self.ds = DatasourceService(session)
        self.value_maps = {}

    def query(self, ds, sql, **params):
        return self.ds.query('DS_' + ds, sql, params)

    def first(self, ds, table, column, value):
        rows = self.query(ds, f'SELECT * FROM {table} WHERE {column}=:value', value=value)
        return rows[0] if rows else None

    def decode(self, ds, table, column, raw):
        if raw is None:
            return '-'
        key = (ds, table, column)
        if key not in self.value_maps:
            row = self.session.scalars(select(Mapping).where(Mapping.ds_code == 'DS_'+ds, Mapping.table_name == table, Mapping.column_name == column).limit(1)).first()
            try:
                self.value_maps[key] = json.loads(row.value_map) if row and row.value_map else {}
            except (ValueError, TypeError):
                self.value_maps[key] = {}
        return self.value_maps[key].get(string(raw), string(raw))

    def decoded(self, ds, table, column, value, field, source):
        row = self.first(ds, table, column, value)
        if row:
            row[field] = self.decode(ds, table, source, row.get(source))
        return row

    @staticmethod
    def event(timeline, time, system, event, detail, staff=None):
        row = dict(time=time, system=system, event=event, detail=detail)
        if staff is not None and string(staff).strip():
            row['staff'] = string(staff)
        timeline.append(row)

    def patients(self, keyword, page, size):
        where = ' WHERE (patient_name LIKE :kw OR inhos_no LIKE :kw)' if keyword and keyword.strip() else ''
        args = dict(kw=f'%{keyword}%', size=size, offset=(page-1)*size)
        total = self.query('HIS', 'SELECT COUNT(*) AS n FROM inpatient'+where, **args)[0]['n']
        rows = self.query('HIS', 'SELECT * FROM inpatient'+where+' ORDER BY admit_time DESC LIMIT :size OFFSET :offset', **args)
        for row in rows:
            agg = self.query('HIS', "SELECT COUNT(DISTINCT o.order_id) AS order_cnt, IFNULL((SELECT SUM(f.amount) FROM fee_detail f WHERE f.inhos_no=:id AND f.fee_status='1'),0) AS fee_total FROM medical_order o WHERE o.inhos_no=:id", id=row['inhos_no'])[0]
            row.update(orderCount=agg['order_cnt'], feeTotal=agg['fee_total'])
        return page_result(rows, total, page, size)

    def payments(self, patient_id, timeline):
        rows = self.query('CHARGE', 'SELECT * FROM pay_record WHERE inhos_no=:id ORDER BY pay_time', id=patient_id)
        for p in rows:
            p['payTypeName'] = self.decode('CHARGE', 'pay_record', 'pay_type', p.get('pay_type'))
            self.event(timeline, p.get('pay_time'), '收费', p['payTypeName'], f"¥{p['amount']}｜{p['channel']}")
        return rows

    def loop(self, inhos_no):
        visit = self.first('HIS', 'inpatient', 'inhos_no', inhos_no)
        if not visit:
            raise BizException('住院就诊不存在: '+inhos_no)
        timeline, loops = [], []
        self.event(timeline, visit.get('admit_time'), 'HIS', '入院登记', f"{visit['dept']} / {visit['ward']}，主管医生 {visit['doctor']}", visit.get('doctor'))
        for o in self.query('HIS', 'SELECT * FROM medical_order WHERE inhos_no=:id ORDER BY create_time', id=inhos_no):
            oid, name = o['order_id'], o['item_name']
            loop = {k: o.get(v) for k, v in dict(orderId='order_id', itemCode='item_code', itemName='item_name', orderType='order_type', orderStatus='order_status', doctor='doctor', createTime='create_time', cancelTime='cancel_time').items()}
            loop['orderStatusName'] = self.decode('HIS', 'medical_order', 'order_status', o.get('order_status'))
            self.event(timeline, o.get('create_time'), 'HIS', '医嘱开立', f"{o['order_type']}｜{name}｜{o['doctor']}", o.get('doctor'))
            fee = self.decoded('HIS', 'fee_detail', 'order_id', oid, 'feeStatusName', 'fee_status')
            if fee:
                loop['fee'] = fee
                self.event(timeline, fee.get('charge_time'), 'HIS', '费用计费', f"{name} ¥{fee['amount']}")
            apply = self.decoded('LIS', 'lab_apply', 'order_id', oid, 'statusName', 'apply_status')
            if apply:
                loop['labApply'] = apply
                self.event(timeline, apply.get('apply_time'), 'LIS', '检验申请', string(apply.get('item_name')))
                if string(apply.get('apply_status')) != 'N':
                    self.event(timeline, apply.get('update_time'), 'LIS', '申请'+apply['statusName'], '申请号 '+string(apply.get('apply_id')))
                report = self.decoded('LIS', 'lab_report', 'apply_id', apply['apply_id'], 'statusName', 'result_status')
                if report:
                    loop['labReport'] = report
                    self.event(timeline, report.get('report_time'), 'LIS', '检验报告发布', f"{name}｜结果{report['statusName']}｜{report['reporter']}", report.get('reporter'))
            review = self.first('PHARMACY', 'presc_review', 'order_id', oid)
            if review:
                loop['prescReview'] = review
                suffix = '｜'+string(review.get('reject_reason')) if review.get('review_result') == '驳回' else ''
                self.event(timeline, review.get('review_time'), '药房', '处方审核'+string(review.get('review_result')), f"{name}｜药师 {review['pharmacist']}"+suffix, review.get('pharmacist'))
            dispense = self.decoded('PHARMACY', 'dispense_record', 'order_id', oid, 'statusName', 'status')
            if dispense:
                loop['dispense'] = dispense
                self.event(timeline, dispense.get('dispense_time'), '药房', dispense['statusName'], f"{name}｜药师 {dispense['pharmacist']}", dispense.get('pharmacist'))
            exam = self.decoded('PACS', 'exam_report', 'order_id', oid, 'abnormalName', 'abnormal_flag')
            if exam:
                loop['examReport'] = exam
                self.event(timeline, exam.get('exam_time'), 'PACS', '检查执行', f"{name}｜技师 {exam['technician']}", exam.get('technician'))
                self.event(timeline, exam.get('report_time'), 'PACS', '检查报告发布', f"{exam['abnormalName']}｜{exam['conclusion']}｜审核 {exam['reviewer']}", exam.get('reviewer'))
            nurse = self.decoded('NURSE', 'nurse_exec', 'order_id', oid, 'execStatusName', 'exec_status')
            if nurse:
                loop['nurseExec'] = nurse
                self.event(timeline, nurse.get('exec_time'), '护士站', '执行确认', f"{nurse['exec_type']}｜{nurse['nurse']}", nurse.get('nurse'))
            if o.get('cancel_time') is not None:
                self.event(timeline, o['cancel_time'], 'HIS', '医嘱取消', string(name))
            status = self.loop_status(o, fee, loop.get('labReport'), dispense, exam)
            loop.update(loopStatus=status, loopStatusName={'BROKEN': '异常中断', 'CLOSED_CANCELED': '已取消闭环', 'CLOSED': '已闭环'}.get(status, '进行中'))
            loops.append(loop)
        payments = self.payments(inhos_no, timeline)
        settlement = self.first('CHARGE', 'settlement', 'inhos_no', inhos_no)
        if settlement:
            self.event(timeline, settlement.get('settle_time'), '收费', '出院结算', '总额 ¥'+string(settlement.get('total_amount')))
        if visit.get('discharge_time') is not None:
            self.event(timeline, visit['discharge_time'], 'HIS', '出院', '')
        timeline.sort(key=lambda e: string(e['time']))
        return dict(visit=visit, orders=loops, payments=payments, settlement=settlement, timeline=timeline)

    @staticmethod
    def loop_status(order, fee, report, dispense, exam=None):
        status = string(order.get('order_status'))
        if status == '2':
            return 'CLOSED_CANCELED' if fee and string(fee.get('fee_status')) == '2' else 'BROKEN'
        if status == '0':
            return 'PENDING'
        executed = report is not None or exam is not None or (dispense is not None and dispense.get('statusName') == '已发药')
        return 'CLOSED' if executed and fee is not None else 'PENDING'

    def staff_detail(self, raw_name):
        name = (raw_name or '').strip()
        for prefix in ('影像医师', '库管员', '麻醉师', '检验师', '医生', '护士', '药师', '技师', '审核'):
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
                break
        staff = self.first('HIS', 'staff', 'staff_name', name)
        if not staff:
            return dict(queryName=raw_name, found=False)
        dept = self.first('HIS', 'dept', 'dept_code', staff['dept_code'])
        colleagues = self.query('HIS', 'SELECT staff_id,staff_name,role,title FROM staff WHERE dept_code=:dept AND staff_id<>:id ORDER BY staff_id', dept=staff['dept_code'], id=staff['staff_id'])
        footprint = {}
        for label, ds, table, where, value in [
            ('开立医嘱', 'HIS', 'medical_order', 'doctor=:name', name),
            ('主管在院患者', 'HIS', 'inpatient', "doctor=:name AND status='在院'", name),
            ('执行确认', 'NURSE', 'nurse_exec', 'nurse LIKE :name', '%'+name),
            ('处方审核', 'PHARMACY', 'presc_review', 'pharmacist=:name', name),
            ('调剂发药', 'PHARMACY', 'dispense_record', 'pharmacist=:name', name),
        ]:
            footprint[label] = self.query(ds, f'SELECT COUNT(*) AS n FROM {table} WHERE {where}', name=value)[0]['n']
        return dict(queryName=raw_name, found=True, staff=staff, dept=dept, colleagues=colleagues, footprint=footprint)

    def opd_patients(self, keyword, page, size):
        where = ' WHERE (r.pat_name LIKE :kw OR r.pat_card_no LIKE :kw)' if keyword and keyword.strip() else ''
        args = dict(kw=f'%{keyword}%', size=size, offset=(page-1)*size)
        total = self.query('OPD', 'SELECT COUNT(*) AS n FROM opd_reg r'+where, **args)[0]['n']
        rows = self.query('OPD', 'SELECT r.*,v.visit_id,v.diag,v.status AS visit_status FROM opd_reg r LEFT JOIN opd_visit v ON v.card_no=r.pat_card_no'+where+' ORDER BY r.reg_time DESC LIMIT :size OFFSET :offset', **args)
        for row in rows:
            agg = self.query('OPD', "SELECT COUNT(*) AS presc_cnt,IFNULL(SUM(CASE WHEN presc_status='3' THEN price END),0) AS exec_total FROM opd_presc WHERE card_no=:id", id=row['pat_card_no'])[0]
            row.update(prescCount=agg['presc_cnt'], execTotal=agg['exec_total'], regStatusName=self.decode('OPD', 'opd_reg', 'reg_status', row.get('reg_status')))
        return page_result(rows, total, page, size)

    def opd_loop(self, card_no):
        reg = self.decoded('OPD', 'opd_reg', 'pat_card_no', card_no, 'regStatusName', 'reg_status')
        if not reg:
            raise BizException('就诊卡号不存在: '+card_no)
        timeline, loops = [], []
        self.event(timeline, reg.get('reg_time'), '门诊', '挂号', f"{reg['reg_dept']}｜{reg['reg_doctor']}｜挂号费 ¥{reg['reg_fee']}", reg.get('reg_doctor'))
        if string(reg.get('reg_status')) == '2':
            self.event(timeline, reg.get('reg_time'), '门诊', '退号', '挂号费原路退回')
        visit = self.decoded('OPD', 'opd_visit', 'card_no', card_no, 'statusName', 'status')
        if visit:
            self.event(timeline, visit.get('visit_time'), '门诊', '看诊', f"诊断：{visit['diag']}｜{visit['doctor']}", visit.get('doctor'))
        for p in self.query('OPD', 'SELECT * FROM opd_presc WHERE card_no=:id ORDER BY create_time', id=card_no):
            pid, name = p['presc_id'], p['item_name']
            loop = {k: p.get(v) for k, v in dict(prescId='presc_id', itemCode='item_code', itemName='item_name', itemType='item_type', quantity='quantity', price='price', prescStatus='presc_status', createTime='create_time').items()}
            loop['statusName'] = self.decode('OPD', 'opd_presc', 'presc_status', p.get('presc_status'))
            self.event(timeline, p.get('create_time'), '门诊', '处方开立', f"{p['item_type']}｜{name} ×{p['quantity']}")
            apply = self.decoded('LIS', 'lab_apply', 'order_id', pid, 'statusName', 'apply_status')
            if apply:
                loop['labApply'] = apply
                self.event(timeline, apply.get('update_time'), 'LIS', '检验'+apply['statusName'], string(apply.get('item_name')))
                report = self.first('LIS', 'lab_report', 'apply_id', apply['apply_id'])
                if report:
                    loop['labReport'] = report
                    self.event(timeline, report.get('report_time'), 'LIS', '检验报告发布', string(name))
            dispense = self.decoded('PHARMACY', 'dispense_record', 'order_id', pid, 'statusName', 'status')
            if dispense:
                loop['dispense'] = dispense
                self.event(timeline, dispense.get('dispense_time'), '药房', dispense['statusName'], f"{name}｜药师 {dispense['pharmacist']}", dispense.get('pharmacist'))
            exam = self.decoded('PACS', 'exam_report', 'order_id', pid, 'abnormalName', 'abnormal_flag')
            if exam:
                loop['examReport'] = exam
                self.event(timeline, exam.get('report_time'), 'PACS', '检查报告发布', f"{exam['abnormalName']}｜{exam['conclusion']}")
            status = {'0': 'CLOSED_CANCELED', '3': 'CLOSED', '2': 'PENDING'}.get(string(p.get('presc_status')), 'UNPAID')
            loop.update(loopStatus=status, loopStatusName={'CLOSED_CANCELED': '已作废闭环', 'CLOSED': '已闭环', 'PENDING': '已缴费待执行', 'UNPAID': '待缴费'}[status])
            loops.append(loop)
        payments = self.payments(card_no, timeline)
        timeline.sort(key=lambda e: string(e['time']))
        return dict(register=reg, visit=visit, prescriptions=loops, payments=payments, timeline=timeline)
