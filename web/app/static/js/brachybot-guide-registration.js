(function (root) {
  'use strict';
  const labels = {
    en: {title: 'Printed guide placement', guide: 'Source guide version', print: 'Physical printed guide ID',
      method: 'Registration evidence', auto: 'Visible guide first; otherwise image registration',
      visible_guide: 'Reconstruct visible guide in current CT', image_rigid: 'Preoperative/current image rigid registration',
      roi: 'Visible guide ROI: x0,y0,z0,x1,y1,z1 (voxel indices)', threshold: 'Visible guide material threshold (HU)',
      residual: 'Maximum surface residual (mm)', ambiguity: 'Ambiguity margin (mm)',
      register: 'Estimate placement', cancel: 'Cancel registration', load: 'Display fit overlays',
      accept: 'Confirm guide fit', reject: 'Reject placement', note: 'Review note', profile: 'Review profile ID',
      confirm: 'I checked the physical printed guide identity and the displayed fit',
      pending: 'Review required. Cyan: positioned printed guide; magenta: observed guide; grey: current CT surface.',
      warning: 'Anatomy registration estimates a rigid guide pose. Soft-tissue deformation and printed strength need separate validation.',
      failed: 'Registration or review failed', noSource: 'Select an intraoperative timepoint with a preoperative source.',
      originalVerified: 'Original printed-guide acquisition verified',
      originalLegacy: 'Legacy source image: historical acquisition identity is not verified',
      originalDirect: 'Direct guide evidence: no preoperative image registration',
      originalRecovery: 'If original source evidence is unavailable, restore the original upload and linked Planning record, or reconstruct a visible guide using an explicit current-CT ROI. Re-estimate and review before using a pose.',
      ambiguous: 'Ambiguous or failed fit: obtain new evidence before acceptance.', select: 'Placement candidate',
      empty: 'No placement candidates', reload: 'Refresh guide placement', drag: 'Drag to rotate the 3D overlay',
      dimensions: 'Current CT and rigid guide overlay: sagittal, coronal, axial and 3D',
      queued: 'Registration queued', running: 'Registration running', completed: 'Placement estimate saved; review required',
      cancelled: 'Registration cancelled', interrupted: 'Registration interrupted; start a new request',
      timed_out: 'Registration time limit reached', stale: 'Registration inputs changed; reload',
      accepted: 'Guide fit confirmed', rejected: 'Guide placement rejected', bores: 'realized bores',
      image_rigid_method: 'Estimated rigid anatomy pose', manual_rigid: 'Manual rigid guide pose',
      visible_guide_multistart_rigid_icp_v1: 'Reconstructed guide surface fit',
      simpleitk_anatomy_rigid_estimated_guide_pose_v1: 'Estimated rigid anatomy pose',
      corresponding_landmarks_se3_v1: 'Corresponding guide landmarks'},
    zh: {title: '已打印导板定位', guide: '源导板版本', print: '实际打印导板标识', method: '配准证据',
      auto: '优先术中可见导板，否则影像配准', visible_guide: '重建当前 CT 中可见导板', image_rigid: '术前／当前影像刚体配准',
      roi: '可见导板区域：x0,y0,z0,x1,y1,z1（体素索引）', threshold: '导板材料阈值（HU）',
      residual: '最大表面残差（mm）', ambiguity: '多解判定差值（mm）', register: '估计定位',
      cancel: '取消配准', load: '显示贴合叠加', accept: '确认导板贴合', reject: '拒绝定位',
      note: '复核说明', profile: '复核配置标识', confirm: '我已核对实际打印导板标识和显示的贴合情况',
      pending: '需要复核。青色：定位后的打印导板；洋红色：术中观察导板；灰色：当前 CT 表面。',
      warning: '影像配准仅估计导板刚体位姿。软组织形变和打印强度需要单独验证。', failed: '配准或复核失败',
      noSource: '请选择关联术前来源的术中时间点。', ambiguous: '存在多解或贴合失败：请补充证据后重新估计。',
      originalVerified: '已核验制作打印导板的原始影像',
      originalLegacy: '旧版来源影像：尚未核验历史采集身份',
      originalDirect: '直接导板证据：未使用术前影像配准',
      originalRecovery: '原始来源证据不可用时，请恢复原始上传及关联计划记录，或明确当前 CT 中可见导板的区域进行重建。使用定位前须重新估计并复核。',
      select: '定位候选', empty: '暂无定位候选', reload: '刷新导板定位', drag: '拖动旋转三维叠加',
      dimensions: '当前 CT 与刚体导板叠加：矢状、冠状、轴向及三维',
      queued: '配准任务排队中', running: '正在配准', completed: '已保存定位估计，需要复核',
      cancelled: '已取消配准', interrupted: '配准已中断，请发起新请求', timed_out: '配准达到时间限制',
      stale: '配准输入已变化，请刷新', accepted: '已确认导板贴合', rejected: '已拒绝导板定位', bores: '已实现孔道',
      image_rigid_method: '解剖刚体位姿估计', manual_rigid: '手动导板刚体位姿',
      visible_guide_multistart_rigid_icp_v1: '重建导板表面贴合',
      simpleitk_anatomy_rigid_estimated_guide_pose_v1: '解剖刚体位姿估计',
      corresponding_landmarks_se3_v1: '对应导板标志点'}
  };
  const same = (a, b) => !!a && !!b && a.session_id === b.session_id && a.timepoint_id === b.timepoint_id && a.mount_generation === b.mount_generation;
  const sameImage = (a, b) => !!a && !!b && ['image_id', 'image_revision', 'geometry_id'].every(k => a[k] === b[k]);

  class GuideRegistrationController {
    constructor(options) {
      this.options = options;
      this.container = options.container;
      this.generation = 0; this.capture = null; this.overlay = null; this.timer = null;
      this.localize = () => {
        if (!this.capture) return;
        const t = this.words();
        this.container.querySelectorAll('[data-guide-label]').forEach(node => {
          const text = t[node.dataset.guideLabel];
          if (node.firstChild && node.firstChild.nodeType === 3) node.firstChild.nodeValue = text;
          else node.prepend(document.createTextNode(text));
        });
        this.localizeInventory();
        this.showSourceProvenance();
        if (this.statusKey) this.status(t[this.statusKey] || t.failed);
      };
      if (root.addEventListener) root.addEventListener('i18nchange', this.localize);
    }
    words() { return labels[(typeof this.options.language === 'function' ? this.options.language() : this.options.language) === 'zh' ? 'zh' : 'en']; }
    current(capture) { return same(capture, this.capture) && (!this.options.getCapture || same(capture, this.options.getCapture())); }
    base(capture) { return '/api/sessions/' + encodeURIComponent(capture.session_id) + '/timepoints/' + encodeURIComponent(capture.timepoint_id) + '/guide-registration'; }
    async call(capture, suffix, method, data) {
      const response = await this.options.request(this.base(capture) + suffix, {method: method || 'GET', body: data, capture});
      if (!response || !response.success) throw new Error(response && response.error || this.words().failed);
      return response;
    }
    element(tag, text, parent) { const node = document.createElement(tag); if (text) {
      node.textContent = text; const key = Object.keys(this.words()).find(key => this.words()[key] === text);
      if (key) node.dataset.guideLabel = key;
    } if (parent) parent.appendChild(node); return node; }
    field(name, text, value, type) {
      const label = this.element('label', text, this.form); label.style.cssText = 'display:flex;flex-direction:column;gap:4px;';
      const input = this.element(type === 'select' ? 'select' : type === 'textarea' ? 'textarea' : 'input', '', label);
      input.name = name; if (input.tagName === 'INPUT') input.type = type || 'text'; if (value !== undefined) input.value = value;
      input.style.cssText = 'color:inherit;background:var(--bg-secondary,#17202d);border:1px solid #64748b;border-radius:5px;padding:6px;min-width:0;';
      this.fields[name] = input; return input;
    }
    button(text, action, parent) {
      const button = this.element('button', text, parent || this.actions); button.type = 'button';
      button.style.cssText = 'padding:6px 10px;border:1px solid #64748b;border-radius:5px;cursor:pointer;';
      button.addEventListener('click', () => Promise.resolve(action()).catch(error => this.status(error.message)));
      return button;
    }
    status(text) { if (this.message) this.message.textContent = text; }
    showSourceProvenance() {
      if (!this.provenance) return;
      const source = this.overlay && this.overlay.source_provenance, t = this.words();
      if (!this.overlay) { this.provenance.textContent = t.originalRecovery; delete this.provenance.dataset.sourceVerified; return; }
      const verified = source && source.original_acquisition_verified === true;
      const caption = source ? (verified ? t.originalVerified : t.originalLegacy) : t.originalDirect;
      const identity = source && source.image && source.image.image_id;
      this.provenance.textContent = caption + (identity ? ' · ' + identity : '');
      this.provenance.dataset.sourceVerified = verified ? 'true' : 'false';
    }
    clear() {
      if (this.timer) clearTimeout(this.timer); this.timer = null;
      if (this.overlay && this.options.clearOverlay) this.options.clearOverlay(this.capture);
      this.overlay = null; this.receipt = null;
      this.showSourceProvenance();
      if (this.views) this.views.replaceChildren();
    }
    async mount(capture) {
      this.clear(); this.capture = Object.freeze({...capture}); this.generation++;
      this.fields = {}; this.container.replaceChildren(); const t = this.words();
      this.container.style.cssText = 'padding:12px;display:flex;flex-direction:column;gap:10px;color:var(--text-primary,#e2e8f0);';
      this.element('h3', t.title, this.container);
      this.form = this.element('div', '', this.container); this.form.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;';
      this.field('guide_version', t.guide, undefined, 'select');
      this.field('manufactured_guide_id', t.print, '', 'text').maxLength = 160;
      const method = this.field('method', t.method, undefined, 'select');
      ['auto', 'visible_guide', 'image_rigid'].forEach(value => { const option = this.element('option', t[value], method); option.value = value; });
      this.field('guide_roi_index_xyz', t.roi, '', 'text'); this.field('guide_threshold_hu', t.threshold, '200', 'number');
      this.field('max_residual_mm', t.residual, '2', 'number'); this.field('ambiguity_margin_mm', t.ambiguity, '0.25', 'number');
      this.field('placement_id', t.select, undefined, 'select');
      this.actions = this.element('div', '', this.container); this.actions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;';
      this.startButton = this.button(t.register, () => this.startJob()); this.cancelButton = this.button(t.cancel, () => this.cancelJob());
      this.button(t.reload, () => this.refresh()); this.button(t.load, () => this.showOverlay());
      this.message = this.element('div', t.warning, this.container); this.message.setAttribute('role', 'status');
      this.provenance = this.element('div', t.originalRecovery, this.container);
      this.provenance.dataset.guideSourceProvenance = '';
      this.views = this.element('div', '', this.container); this.views.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;';
      this.field('profile_id', t.profile, '', 'text'); this.field('note', t.note, '', 'textarea').maxLength = 1000;
      const confirm = this.element('label', '', this.container); this.confirm = this.element('input', '', confirm); this.confirm.type = 'checkbox'; this.element('span', t.confirm, confirm);
      this.reviewActions = this.element('div', '', this.container); this.reviewActions.style.cssText = 'display:flex;gap:8px;';
      this.acceptButton = this.button(t.accept, () => this.review('accepted'), this.reviewActions); this.acceptButton.disabled = true;
      this.rejectButton = this.button(t.reject, () => this.review('rejected'), this.reviewActions);
      this.cancelButton.disabled = true;
      await this.refresh();
    }
    localizeInventory() {
      if (!this.inventory) return;
      const t = this.words();
      [...this.fields.guide_version.options].forEach((option, i) => {
        const guide = this.inventory.guide_versions[i]; if (guide) option.textContent = 'v' + guide.guide_version + ' · ' + guide.eligible_bore_count + ' ' + t.bores;
      });
      [...this.fields.placement_id.options].forEach((option, i) => {
        const row = this.inventory.candidates[i]; if (row) option.textContent = (t[row.method] || t.image_rigid_method) + ' · ' + (t[row.review_state] || t.pending);
      });
    }
    async refresh() {
      const capture = this.capture; const response = await this.call(capture, ''); if (!this.current(capture)) return;
      this.inventory = response;
      const select = this.fields.guide_version; const old = select.value; select.replaceChildren();
      response.guide_versions.forEach(guide => { const option = this.element('option', 'v' + guide.guide_version + ' · ' + guide.eligible_bore_count + ' bores', select); option.value = guide.guide_version; });
      if (old) select.value = old;
      this.fields.placement_id.replaceChildren();
      response.candidates.forEach(row => { const option = this.element('option', row.method + ' · ' + row.review_state, this.fields.placement_id); option.value = row.placement_id; });
      this.localizeInventory();
      if (response.review_profile && response.review_profile.confirmed_by) {
        this.fields.profile_id.value = response.review_profile.profile_id;
        this.fields.profile_id.readOnly = true;
      }
      this.startButton.disabled = !response.source_timepoint_id || !select.options.length;
      if (!response.source_timepoint_id) this.status(this.words().noSource);
    }
    async startJob() {
      const capture = this.capture; this.clear(); this.acceptButton.disabled = true;
      const data = {request_id: crypto.randomUUID(), source_timepoint_id: this.inventory.source_timepoint_id,
        guide_version: Number(this.fields.guide_version.value), manufactured_guide_id: this.fields.manufactured_guide_id.value.trim(),
        expected_state_revision: this.inventory.state_revision, method: this.fields.method.value,
        max_residual_mm: Number(this.fields.max_residual_mm.value), ambiguity_margin_mm: Number(this.fields.ambiguity_margin_mm.value)};
      if(Number.isInteger(this.inventory.clinical_revision)) data.expected_clinical_revision=this.inventory.clinical_revision;
      if (this.fields.guide_roi_index_xyz.value.trim()) {
        data.guide_roi_index_xyz = this.fields.guide_roi_index_xyz.value.split(',').map(Number);
        data.guide_threshold_hu = Number(this.fields.guide_threshold_hu.value);
      }
      const response = await this.call(capture, '/jobs', 'POST', data); if (!this.current(capture)) return;
      this.job = response.job; this.startButton.disabled = true; this.cancelButton.disabled = false;
      await this.poll(capture);
    }
    async poll(capture) {
      if (!this.current(capture)) return;
      const response = await this.call(capture, '/jobs/' + encodeURIComponent(this.job.job_id)); if (!this.current(capture)) return;
      this.job = response.job; this.statusKey = this.job.status;
      this.status((this.words()[this.job.status] || this.words().failed) + (this.job.error ? ': ' + this.job.error : ''));
      if (['queued', 'running'].includes(this.job.status)) { this.timer = setTimeout(() => this.poll(capture).catch(error => this.status(error.message)), 800); return; }
      this.cancelButton.disabled = true; await this.refresh();
      if (this.job.status === 'completed') { this.fields.placement_id.value = this.job.placement_id; await this.showOverlay(); }
    }
    async cancelJob() { if (this.job) await this.call(this.capture, '/jobs/' + encodeURIComponent(this.job.job_id) + '/cancel', 'POST', {}); }
    async showOverlay() {
      const capture = this.capture, placement = this.fields.placement_id.value;
      if (!placement) { this.status(this.words().empty); return; }
      const selected = this.inventory.candidates.find(row => row.placement_id === placement);
      const version = selected && selected.qc.service_scope.guide_version || Number(this.fields.guide_version.value);
      const response = await this.call(capture, '/placements/' + encodeURIComponent(placement) + '/overlay?guide_version=' + version);
      if (!this.current(capture)) return;
      this.clear(); this.overlay = response.overlay; this.overlay.guide_version = version;
      this.showSourceProvenance();
      this.drawSlices(this.overlay);
      this.draw3D(this.overlay);
      let displayed = {displayed: true, dimensions: ['2d', '3d'], target_image: this.overlay.target_image};
      if (this.options.renderOverlay) displayed = await this.options.renderOverlay(this.overlay, capture);
      if (!this.current(capture)) { if (this.options.clearOverlay) this.options.clearOverlay(capture); return; }
      if (displayed && displayed.displayed === true && ['2d', '3d'].every(dim => displayed.dimensions.includes(dim)) && sameImage(displayed.target_image, this.overlay.target_image)) {
        this.receipt = {session_id: capture.session_id, timepoint_id: capture.timepoint_id, placement_id: placement,
          candidate_sha256: this.overlay.candidate_sha256, target_image: this.overlay.target_image,
          state_revision: this.overlay.state_revision, dimensions: ['2d', '3d'], receipt_token: this.overlay.receipt_token};
        if(Number.isInteger(this.overlay.clinical_revision)) this.receipt.clinical_revision=this.overlay.clinical_revision;
      }
      this.acceptButton.disabled = !this.receipt || this.overlay.qc.ambiguous || this.overlay.qc.fit_failed;
      this.confirm.checked = false;
      this.statusKey = this.overlay.qc.ambiguous || this.overlay.qc.fit_failed ? 'ambiguous' : 'pending';
      this.status(this.words()[this.statusKey]);
    }
    drawSlices(packet) {
      packet.slices.forEach(slice => {
        const holder = this.element('div', '', this.views); this.element('div', slice.name + ' · ' + slice.index, holder);
        const canvas = this.element('canvas', '', holder); canvas.width = slice.width; canvas.height = slice.height;
        canvas.style.cssText = 'width:100%;image-rendering:pixelated;border:1px solid #64748b;';
        const context = canvas.getContext('2d'), image = context.createImageData(slice.width, slice.height);
        const source = slice.registered_source_hu && slice.registered_source_hu.flat();
        slice.ct_hu.flat().forEach((hu, index) => { const x = index % slice.width, y = Math.floor(index / slice.width);
          const sample = source && (Math.floor(x / 8) + Math.floor(y / 8)) % 2 ? source[index] : hu;
          const grey = Math.max(0, Math.min(255, (sample + 600) * 255 / 1400)); image.data.set([grey, grey, grey, 255], index * 4); });
        context.putImageData(image, 0, 0); context.strokeStyle = '#22d3ee'; context.lineWidth = .7;
        slice.guide_segments_pixels.forEach(segment => { context.beginPath(); context.moveTo(...segment[0]); context.lineTo(...segment[1]); context.stroke(); });
      });
    }
    draw3D(packet) {
      const holder = this.element('div', '', this.views); this.element('div', '3D · ' + this.words().drag, holder);
      const canvas = this.element('canvas', '', holder); canvas.width = 360; canvas.height = 300; canvas.style.cssText = 'width:100%;border:1px solid #64748b;touch-action:none;';
      const context = canvas.getContext('2d'); let yaw = .5, pitch = -.35, drag = null;
      const meshes = [{vertices_lps_mm: packet.vertices_lps_mm, faces: packet.faces, color: '#22d3ee', alpha: .85},
        {...(packet.current_body_surface || {}), color: '#cbd5e1', alpha: .13}, {...(packet.observed_surface || {}), color: '#e879f9', alpha: .7}].filter(mesh => mesh.vertices_lps_mm);
      const points = meshes.flatMap(mesh => mesh.vertices_lps_mm);
      const low = [0, 1, 2].map(i => Math.min(...points.filter((_, n) => n % Math.max(1, Math.floor(points.length / 40000)) === 0).map(p => p[i])));
      const high = [0, 1, 2].map(i => Math.max(...points.filter((_, n) => n % Math.max(1, Math.floor(points.length / 40000)) === 0).map(p => p[i])));
      const center = low.map((value, i) => (value + high[i]) / 2), scale = 240 / Math.max(...high.map((value, i) => value - low[i]), 1);
      const draw = () => {
        context.fillStyle = '#0f172a'; context.fillRect(0, 0, canvas.width, canvas.height);
        const project = point => { let [x, y, z] = point.map((value, i) => value - center[i]); const a = x * Math.cos(yaw) - y * Math.sin(yaw), b = x * Math.sin(yaw) + y * Math.cos(yaw); return [180 + scale * a, 150 - scale * (z * Math.cos(pitch) - b * Math.sin(pitch))]; };
        meshes.slice().reverse().forEach(mesh => {
          context.strokeStyle = mesh.color; context.globalAlpha = mesh.alpha; context.lineWidth = .45;
          const stride = Math.max(1, Math.ceil(mesh.faces.length / 12000));
          for (let i = 0; i < mesh.faces.length; i += stride) { const polygon = mesh.faces[i].map(id => project(mesh.vertices_lps_mm[id])); context.beginPath(); context.moveTo(...polygon[0]); context.lineTo(...polygon[1]); context.lineTo(...polygon[2]); context.closePath(); context.stroke(); }
        }); context.globalAlpha = 1;
      };
      canvas.addEventListener('pointerdown', event => { drag = [event.clientX, event.clientY]; canvas.setPointerCapture(event.pointerId); });
      canvas.addEventListener('pointermove', event => { if (!drag) return; yaw += (event.clientX - drag[0]) / 100; pitch += (event.clientY - drag[1]) / 100; drag = [event.clientX, event.clientY]; draw(); });
      canvas.addEventListener('pointerup', () => { drag = null; }); draw();
    }
    async review(decision) {
      const capture = this.capture;
      if (!this.overlay) throw new Error(this.words().empty);
      if (decision === 'accepted' && (!this.receipt || !this.confirm.checked)) throw new Error(this.words().confirm);
      const data = {guide_version: this.overlay.guide_version, expected_state_revision: this.overlay.state_revision,
        candidate_sha256: this.overlay.candidate_sha256, decision, profile_id: this.fields.profile_id.value.trim(),
        note: this.fields.note.value.trim(), overlay_receipt: this.receipt, manufacturing_confirmed: this.confirm.checked};
      if (Number.isInteger(this.overlay.clinical_revision)) data.expected_clinical_revision=this.overlay.clinical_revision;
      const response = await this.call(capture, '/placements/' + encodeURIComponent(this.overlay.placement_id) + '/review', 'POST', data);
      if (!this.current(capture)) return;
      this.clear(); this.acceptButton.disabled = true; this.statusKey = response.placement.review_state;
      this.status(this.words()[this.statusKey]); await this.refresh();
      if (this.options.onReview) this.options.onReview(response, capture);
    }
    unmount() { this.clear(); this.capture = null; this.generation++; this.container.replaceChildren();
      if (root.removeEventListener) root.removeEventListener('i18nchange', this.localize); }
  }
  root.BrachyGuideRegistration = {GuideRegistrationController, sameScope: same};
  if (typeof module !== 'undefined') module.exports = root.BrachyGuideRegistration;
})(typeof window !== 'undefined' ? window : globalThis);
