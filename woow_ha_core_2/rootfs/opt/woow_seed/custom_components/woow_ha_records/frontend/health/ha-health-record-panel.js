// Custom panel using vanilla web components (no external dependencies)
class HaHealthRecordPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this.members = [];
    this.records = [];
    this.loading = true;
    this.startDate = '';
    this.endDate = '';
    this.showInputDialog = false;
    this.selectedMember = null;
    this.selectedType = '';
    this.inputValue = 0;
    this.inputNote = '';
    this.submitting = false;

    // Timestamp for logging (defaults to now)
    this.inputTimestamp = '';

    // Tab state
    this.activeTab = 'record'; // 'record' | 'settings'
    this.expandedRecordId = null;
    this.editingRecord = null; // { value, note, timestamp }
    this.showTypeDialog = false;
    this.editingType = null; // { mode: 'add'|'edit', data: {...} }
    this.showMemberDialog = false;
    this.editingMember = null; // { mode: 'add'|'edit', data: {...} }
    this.showDeleteConfirm = false;
    this.deleteTarget = null; // { type: 'record'|'recordType'|'member', id, name, memberId? }

    // New: Selected member for filtering (like Finance Record's account selector)
    this.selectedMemberId = '';

    // New: Search query
    this.searchQuery = '';

    // Type filter toggles (empty = show all; non-empty = show only matching types)
    this.activeTypeFilters = [];
    // Input dialog mode: '' | 'quick' | 'add'
    this.inputDialogMode = '';

    // Settings section collapse state
    this.settingsMemberCollapsed = true;
    this.settingsTypesCollapsed = true;
    this.settingsDataCollapsed = true;

    // Calendar filter state
    this._filterDateStart = '';   // ISO date string YYYY-MM-DD
    this._filterDateEnd = '';     // ISO date string YYYY-MM-DD
    this._filterCalendarOpen = ''; // 'start' | 'end' | ''
    const now_cal = new Date();
    this._filterCalendarViewMonth = now_cal.getMonth() + 1;
    this._filterCalendarViewYear = now_cal.getFullYear();

    // Localization strings
    this._strings = {
      en: {
        // Header
        title: 'Health Record',
        filter: 'Filter',
        to: 'to',
        search: 'Search...',
        allMembers: 'All Members',
        selectMember: 'Select Member',
        // Tabs
        record: 'Record',
        settings: 'Settings',
        // Sub-tabs
        recordTypes: 'Record Types',
        members: 'Members',
        // Section headers
        memberInfoSection: 'Member Info',
        recordTypesSection: 'Record Types',
        // Timeline
        noMembers: 'No members configured. Go to the Settings tab to add members.',
        noRecords: 'No records for this date range.',
        // Manage
        noMembersManage: 'No members configured. Add a member first.',
        noRecordTypes: 'No record types configured for this member.',
        noMembersYet: 'No members configured yet.',
        member: 'Member',
        unit: 'Unit',
        current: 'Current',
        records_label: 'Records',
        // Buttons
        addRecord: 'Add Record',
        recordType: 'Record Type',
        selectRecordType: 'Select record type',
        addRecordType: '+ Add Record Type',
        addMember: 'Add Member',
        save: 'Save',
        saving: 'Saving...',
        cancel: 'Cancel',
        delete: 'Delete',
        deleting: 'Deleting...',
        // Dialogs
        logFor: 'Log {type} for {name}',
        value: 'Value',
        note: 'Note',
        optionalNote: 'Optional note',
        timestamp: 'Time',
        now: 'Now',
        addRecordTypeTitle: 'Add Record Type',
        editRecordTypeTitle: 'Edit Record Type',
        addMemberTitle: 'Add Member',
        editMemberTitle: 'Edit Member',
        name: 'Name',
        namePlaceholder: 'e.g., Feeding',
        unitPlaceholder: 'e.g., ml',
        defaultValue: 'Default Value',
        defaultValueMode: 'Default Value Mode',
        defaultValueFixed: 'Fixed Value',
        defaultValueLastValue: 'Last Value',
        lastValue: 'Last Value',
        memberNamePlaceholder: 'e.g., Baby Emma',
        memberIdLabel: 'ID (optional, auto-generated from name)',
        memberIdPlaceholder: 'e.g., baby_emma',
        memberNoteLabel: 'Note',
        memberNotePlaceholder: 'Optional notes about this member',
        confirmDelete: 'Confirm Delete',
        confirmDeleteMessage: 'Are you sure you want to delete "{name}"?',
        loading: 'Loading...',
        menu: 'Menu',
        totalRecords: 'Total Records',
        lastRecord: 'Last Record',
        noRecordsYet: 'No records yet',
        recordTypesCount: 'Record Types',
        latestValues: 'Latest Values',
        // Data Management
        dataManagementSection: 'Data Management',
        exportCsv: 'Export CSV',
        exportNoRecords: 'No records to export',
        exportingCsv: 'Exporting...',
        // Calendar
        start_date: 'Start Date',
        end_date: 'End Date',
        january: 'January', february: 'February', march: 'March',
        april: 'April', may_month: 'May', june: 'June',
        july: 'July', august: 'August', september: 'September',
        october: 'October', november: 'November', december: 'December',
        sun: 'Su', mon: 'Mo', tue: 'Tu', wed: 'We', thu: 'Th', fri: 'Fr', sat: 'Sa',
      },
      'zh-Hant': {
        // Header
        title: '健康紀錄',
        filter: '篩選',
        to: '至',
        search: '搜尋...',
        allMembers: '所有成員',
        selectMember: '選擇成員',
        // Tabs
        record: '紀錄',
        settings: '設定',
        // Sub-tabs
        recordTypes: '紀錄類型',
        members: '成員',
        // Section headers
        memberInfoSection: '成員資訊',
        recordTypesSection: '紀錄類型',
        // Timeline
        noMembers: '尚未設定成員。請前往「設定」分頁新增成員。',
        noRecords: '此日期範圍內沒有紀錄。',
        // Manage
        noMembersManage: '尚未設定成員。請先新增成員。',
        noRecordTypes: '此成員尚未設定紀錄類型。',
        noMembersYet: '尚未設定任何成員。',
        member: '成員',
        unit: '單位',
        current: '目前',
        records_label: '紀錄',
        // Buttons
        addRecord: '新增紀錄',
        recordType: '紀錄類型',
        selectRecordType: '選擇紀錄類型',
        addRecordType: '+ 新增紀錄類型',
        addMember: '新增成員',
        save: '儲存',
        saving: '儲存中...',
        cancel: '取消',
        delete: '刪除',
        deleting: '刪除中...',
        // Dialogs
        logFor: '為 {name} 記錄 {type}',
        value: '數值',
        note: '備註',
        optionalNote: '選填備註',
        timestamp: '時間',
        now: '現在',
        addRecordTypeTitle: '新增紀錄類型',
        editRecordTypeTitle: '編輯紀錄類型',
        addMemberTitle: '新增成員',
        editMemberTitle: '編輯成員',
        name: '名稱',
        namePlaceholder: '例如：餵食',
        unitPlaceholder: '例如：ml',
        defaultValue: '預設數值',
        defaultValueMode: '預設數值模式',
        defaultValueFixed: '固定值',
        defaultValueLastValue: '上次數值',
        lastValue: '上次數值',
        memberNamePlaceholder: '例如：寶寶小明',
        memberIdLabel: 'ID（選填，將自動從名稱產生）',
        memberIdPlaceholder: '例如：baby_ming',
        memberNoteLabel: '備註',
        memberNotePlaceholder: '關於此成員的選填備註',
        confirmDelete: '確認刪除',
        confirmDeleteMessage: '確定要刪除「{name}」嗎？',
        loading: '載入中...',
        menu: '選單',
        totalRecords: '總紀錄數',
        lastRecord: '最新紀錄',
        noRecordsYet: '尚無紀錄',
        recordTypesCount: '紀錄類型',
        latestValues: '最新數值',
        // Data Management
        dataManagementSection: '資料管理',
        exportCsv: '匯出 CSV',
        exportNoRecords: '沒有可匯出的紀錄',
        exportingCsv: '匯出中...',
        // Calendar
        start_date: '開始日期',
        end_date: '結束日期',
        january: '一月', february: '二月', march: '三月',
        april: '四月', may_month: '五月', june: '六月',
        july: '七月', august: '八月', september: '九月',
        october: '十月', november: '十一月', december: '十二月',
        sun: '日', mon: '一', tue: '二', wed: '三', thu: '四', fri: '五', sat: '六',
      },
      'zh-Hans': {
        // Header
        title: '健康记录',
        filter: '筛选',
        to: '至',
        search: '搜索...',
        allMembers: '所有成员',
        selectMember: '选择成员',
        // Tabs
        record: '记录',
        settings: '设置',
        // Sub-tabs
        recordTypes: '记录类型',
        members: '成员',
        // Section headers
        memberInfoSection: '成员信息',
        recordTypesSection: '记录类型',
        // Timeline
        noMembers: '尚未设置成员。请前往"设置"标签页添加成员。',
        noRecords: '此日期范围内没有记录。',
        // Manage
        noMembersManage: '尚未设置成员。请先添加成员。',
        noRecordTypes: '此成员尚未设置记录类型。',
        noMembersYet: '尚未设置任何成员。',
        member: '成员',
        unit: '单位',
        current: '当前',
        records_label: '记录',
        // Buttons
        addRecord: '添加记录',
        recordType: '记录类型',
        selectRecordType: '选择记录类型',
        addRecordType: '+ 添加记录类型',
        addMember: '+ 添加成员',
        save: '保存',
        saving: '保存中...',
        cancel: '取消',
        delete: '删除',
        deleting: '删除中...',
        // Dialogs
        logFor: '为 {name} 记录 {type}',
        value: '数值',
        note: '备注',
        optionalNote: '可选备注',
        timestamp: '时间',
        now: '现在',
        addRecordTypeTitle: '添加记录类型',
        editRecordTypeTitle: '编辑记录类型',
        addMemberTitle: '添加成员',
        editMemberTitle: '编辑成员',
        name: '名称',
        namePlaceholder: '例如：喂食',
        unitPlaceholder: '例如：ml',
        defaultValue: '默认数值',
        defaultValueMode: '默认数值模式',
        defaultValueFixed: '固定值',
        defaultValueLastValue: '上次数值',
        lastValue: '上次数值',
        memberNamePlaceholder: '例如：宝宝小明',
        memberIdLabel: 'ID（可选，将自动从名称生成）',
        memberIdPlaceholder: '例如：baby_ming',
        memberNoteLabel: '备注',
        memberNotePlaceholder: '关于此成员的可选备注',
        confirmDelete: '确认删除',
        confirmDeleteMessage: '确定要删除"{name}"吗？',
        loading: '加载中...',
        menu: '菜单',
        totalRecords: '总记录数',
        lastRecord: '最新记录',
        noRecordsYet: '尚无记录',
        recordTypesCount: '记录类型',
        latestValues: '最新数值',
        // Data Management
        dataManagementSection: '数据管理',
        exportCsv: '导出 CSV',
        exportNoRecords: '没有可导出的记录',
        exportingCsv: '导出中...',
        // Calendar
        start_date: '开始日期',
        end_date: '结束日期',
        january: '一月', february: '二月', march: '三月',
        april: '四月', may_month: '五月', june: '六月',
        july: '七月', august: '八月', september: '九月',
        october: '十月', november: '十一月', december: '十二月',
        sun: '日', mon: '一', tue: '二', wed: '三', thu: '四', fri: '五', sat: '六',
      },
    };

    this._lastLanguage = null;

    // Wide fallback range so initial load fetches all records
    this.startDate = '2000-01-01T00:00:00';
    this.endDate = '2099-12-31T23:59:59';
  }

  // Get localized string
  _t(key, replacements = {}) {
    const lang = this._getLanguage();
    const strings = this._strings[lang] || this._strings['en'];
    let str = strings[key] || this._strings['en'][key] || key;

    // Replace placeholders like {name}, {type}
    for (const [k, v] of Object.entries(replacements)) {
      str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
    }
    return str;
  }

  // Get current language, with fallback (Profile Language takes priority)
  _getLanguage() {
    const locale = this._hass?.language || this._hass?.locale?.language || navigator.language || 'en';
    // Check for exact match first
    if (this._strings[locale]) return locale;
    // Check for language prefix (e.g., 'zh-TW' -> 'zh-Hant')
    if (locale.startsWith('zh-TW') || locale.startsWith('zh-HK')) return 'zh-Hant';
    if (locale.startsWith('zh-CN') || locale.startsWith('zh-SG')) return 'zh-Hans';
    if (locale.startsWith('zh')) return 'zh-Hans'; // Default Chinese to Simplified
    return 'en';
  }

  set hass(hass) {
    this._hass = hass;
    if (hass) {
      const currentLang = this._getLanguage();
      if (this._lastLanguage === null) {
        this._lastLanguage = currentLang;
      } else if (currentLang !== this._lastLanguage) {
        this._lastLanguage = currentLang;
        this._render();
      }
      if (this.members.length === 0) {
        this._loadData();
      }
    }
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._render();
    // Close calendar on outside click
    this._onDocumentClick = (e) => {
      if (this._filterCalendarOpen) {
        const path = e.composedPath();
        const inDropdown = path.some(el => el.classList && el.classList.contains('date-picker-wrapper'));
        if (!inDropdown) {
          this._filterCalendarOpen = '';
          this._render();
        }
      }
    };
    document.addEventListener('click', this._onDocumentClick);
  }

  disconnectedCallback() {
    if (this._onDocumentClick) {
      document.removeEventListener('click', this._onDocumentClick);
    }
  }

  _getLocale() {
    return this._hass?.locale?.language || navigator.language || 'en';
  }

  _toLocalISOString(date) {
    const pad = (n) => n.toString().padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  async _loadData() {
    this.loading = true;
    this._render();

    try {
      // Load members
      const membersResult = await this._hass.callWS({
        type: 'woow_ha_records/health/get_members',
      });
      this.members = membersResult.members || [];

      // Auto-select first member if none selected
      if (this.members.length > 0 && !this.selectedMemberId) {
        this.selectedMemberId = this.members[0].id;
      }

      // Load records
      await this._loadRecords();
    } catch (error) {
      console.error('Error loading data:', error);
    }

    this.loading = false;
    this._render();
  }

  async _loadRecords() {
    try {
      const recordsResult = await this._hass.callWS({
        type: 'woow_ha_records/health/get_records',
        start_time: new Date(this.startDate).toISOString(),
        end_time: new Date(this.endDate).toISOString(),
      });
      this.records = recordsResult.records || [];
    } catch (error) {
      console.error('Error loading records:', error);
    }
    this._render();
  }

  _formatTime(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleTimeString(this._getLocale(), {
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  _formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString(this._getLocale(), {
      month: 'short',
      day: 'numeric',
    });
  }

  _formatDateTime(dateStr) {
    const date = new Date(dateStr);
    const locale = this._getLocale();
    const datePart = date.toLocaleDateString(locale, { month: '2-digit', day: '2-digit' });
    const timePart = date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
    return `${datePart} ${timePart}`;
  }

  _generateRecordId(record) {
    // Use UUID if available, otherwise fall back to composite key
    if (record.id) return record.id;
    return `${record.member_id}_${record.record_type}_${record.timestamp}`;
  }

  _openInputDialog(member, recordType, mode = 'quick') {
    this.inputDialogMode = mode;
    this.selectedMember = member;
    this.selectedType = recordType;
    const typeInfo = (member.record_sets || []).find(s => s.type === recordType);
    const useLastValue = typeInfo?.default_value_mode === 'last_value';
    this.inputValue = useLastValue
      ? (typeInfo?.current_value ?? typeInfo?.default_value ?? 0)
      : (typeInfo?.default_value ?? 0);
    this.inputNote = '';
    this.inputTimestamp = this._toLocalISOString(new Date());
    this.showInputDialog = true;
    this._render();
  }

  _openAddRecordDialog() {
    const member = this.members.find(m => m.id === this.selectedMemberId);
    if (!member) return;
    const firstSet = (member.record_sets || [])[0];
    this._openInputDialog(member, firstSet ? firstSet.type : '', 'add');
  }

  _closeInputDialog() {
    this.showInputDialog = false;
    this.selectedMember = null;
    this.selectedType = '';
    this.inputDialogMode = '';
    this._render();
  }

  async _submitInput() {
    if (!this.selectedMember || !this.selectedType || this.submitting) return;

    this.submitting = true;
    this._render();

    try {
      await this._hass.callWS({
        type: 'woow_ha_records/health/log_record',
        member_id: this.selectedMember.id,
        record_type: this.selectedType,
        value: this.inputValue || 0,
        note: this.inputNote || '',
        timestamp: this.inputTimestamp ? new Date(this.inputTimestamp).toISOString() : undefined,
      });

      this._closeInputDialog();
      await this._loadData();
    } catch (error) {
      console.error('Error logging record:', error);
      alert('Failed to log record: ' + error.message);
    }

    this.submitting = false;
    this._render();
  }

  _handleDateChange() {
    // Derive full datetime range; use wide fallback when filter is cleared
    this.startDate = this._filterDateStart
      ? this._toLocalISOString(new Date(this._filterDateStart + 'T00:00:00'))
      : '2000-01-01T00:00:00';
    this.endDate = this._filterDateEnd
      ? this._toLocalISOString(new Date(this._filterDateEnd + 'T23:59:59'))
      : '2099-12-31T23:59:59';
    this._loadRecords();
  }

  // Calendar helper methods (ported from ha_finance for vanilla web component)
  _getFilterCalendarDays(month, year) {
    const daysInMonth = new Date(year, month, 0).getDate();
    const firstDayOfWeek = new Date(year, month - 1, 1).getDay();
    const prevDays = new Date(year, month - 1, 0).getDate();
    const cells = [];
    for (let i = firstDayOfWeek - 1; i >= 0; i--) {
      cells.push({ day: prevDays - i, current: false });
    }
    for (let d = 1; d <= daysInMonth; d++) {
      cells.push({ day: d, current: true });
    }
    let nextDay = 1;
    while (cells.length % 7 !== 0) {
      cells.push({ day: nextDay++, current: false });
    }
    return cells;
  }

  _filterCalendarPrev() {
    if (this._filterCalendarViewMonth === 1) {
      this._filterCalendarViewMonth = 12;
      this._filterCalendarViewYear--;
    } else {
      this._filterCalendarViewMonth--;
    }
    this._render();
  }

  _filterCalendarNext() {
    if (this._filterCalendarViewMonth === 12) {
      this._filterCalendarViewMonth = 1;
      this._filterCalendarViewYear++;
    } else {
      this._filterCalendarViewMonth++;
    }
    this._render();
  }

  _filterCalendarSelectDay(day) {
    const m = String(this._filterCalendarViewMonth).padStart(2, '0');
    const d = String(day).padStart(2, '0');
    const iso = `${this._filterCalendarViewYear}-${m}-${d}`;
    if (this._filterCalendarOpen === 'start') {
      this._filterDateStart = iso;
    } else if (this._filterCalendarOpen === 'end') {
      this._filterDateEnd = iso;
    }
    this._filterCalendarOpen = '';
    this._handleDateChange();
  }

  _formatDateForInput(isoString) {
    if (!isoString) return '';
    try {
      const date = new Date(isoString + 'T00:00:00');
      return date.toLocaleDateString(this._getLocale(), {
        year: 'numeric', month: '2-digit', day: '2-digit'
      });
    } catch { return isoString; }
  }

  _isFilterDateSelected(day, month, year, isoString) {
    if (!isoString) return false;
    const parts = isoString.split('-');
    return parseInt(parts[0]) === year && parseInt(parts[1]) === month && parseInt(parts[2]) === day;
  }

  _renderFilterCalendar(which) {
    const monthNames = ['', 'january', 'february', 'march', 'april', 'may_month', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
    const weekdays = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
    const viewMonth = this._filterCalendarViewMonth;
    const viewYear = this._filterCalendarViewYear;
    const cells = this._getFilterCalendarDays(viewMonth, viewYear);
    const selectedIso = which === 'start' ? this._filterDateStart : this._filterDateEnd;

    let html = `<div class="date-picker-dropdown" data-calendar-dropdown>
      <div class="calendar-widget">
        <div class="calendar-header">
          <button type="button" data-calendar-prev>&lsaquo;</button>
          <span>${this._t(monthNames[viewMonth])} ${viewYear}</span>
          <button type="button" data-calendar-next>&rsaquo;</button>
        </div>
        <div class="calendar-weekdays">`;
    for (const wd of weekdays) {
      html += `<span>${this._t(wd)}</span>`;
    }
    html += `</div><div class="calendar-days">`;
    for (const cell of cells) {
      if (cell.current) {
        const selected = this._isFilterDateSelected(cell.day, viewMonth, viewYear, selectedIso) ? ' selected' : '';
        html += `<button type="button" class="calendar-day${selected}" data-calendar-day="${cell.day}">${cell.day}</button>`;
      } else {
        html += `<span class="calendar-day other-month">${cell.day}</span>`;
      }
    }
    html += `</div></div></div>`;
    return html;
  }

  // Toggle sidebar
  _toggleSidebar() {
    this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
  }

  // Member selector change
  _onMemberChange(e) {
    this.selectedMemberId = e.target.value;
    this._render();
  }

  // Search input change
  _onSearchInput(e) {
    this.searchQuery = e.target.value;
    const cursorPos = e.target.selectionStart;
    this._render();
    const input = this.shadowRoot.querySelector('#search-input');
    if (input) {
      input.focus();
      input.setSelectionRange(cursorPos, cursorPos);
    }
  }

  // Toggle a record type filter on/off
  _toggleTypeFilter(type) {
    const idx = this.activeTypeFilters.indexOf(type);
    if (idx === -1) {
      this.activeTypeFilters = [...this.activeTypeFilters, type];
    } else {
      this.activeTypeFilters = this.activeTypeFilters.filter(t => t !== type);
    }
    this._render();
  }

  // Get filtered records based on member and search
  _getFilteredRecords() {
    let filtered = [...this.records];

    // Filter by selected member
    if (this.selectedMemberId) {
      filtered = filtered.filter(r => r.member_id === this.selectedMemberId);
    }

    // Filter by active type filters
    if (this.activeTypeFilters.length > 0) {
      filtered = filtered.filter(r => this.activeTypeFilters.includes(r.record_type));
    }

    // Filter by search query
    if (this.searchQuery && this.searchQuery.trim()) {
      const query = this.searchQuery.toLowerCase().trim();
      filtered = filtered.filter(r => {
        const note = (r.note || '').toLowerCase();
        const typeName = (r.record_name || r.record_type || '').toLowerCase();
        const memberName = (r.member_name || '').toLowerCase();
        const val = String(r.value || '');
        return note.includes(query) || typeName.includes(query) || memberName.includes(query) || val.includes(query);
      });
    }

    return filtered;
  }

  // ============================================================================
  // Tab Navigation
  // ============================================================================

  _switchTab(tab) {
    this.activeTab = tab;
    this._render();
  }

  // ============================================================================
  // Inline Record Editing
  // ============================================================================

  _toggleRecordExpand(record) {
    const recordId = this._generateRecordId(record);
    if (this.expandedRecordId === recordId) {
      this.expandedRecordId = null;
      this.editingRecord = null;
    } else {
      this.expandedRecordId = recordId;
      // Convert ISO timestamp to datetime-local format
      const timestamp = record.timestamp ? this._toLocalISOString(new Date(record.timestamp)) : '';
      this.editingRecord = {
        value: record.value || 0,
        note: record.note || '',
        timestamp: timestamp,
      };
    }
    this._render();
  }

  async _saveRecordEdit(record) {
    if (this.submitting) return;
    this.submitting = true;
    this._render();

    try {
      // Convert datetime-local value to ISO string for new_timestamp
      const newTimestamp = this.editingRecord.timestamp ? new Date(this.editingRecord.timestamp).toISOString() : null;
      await this._hass.callWS({
        type: 'woow_ha_records/health/update_record',
        member_id: record.member_id,
        type_id: record.record_type,
        timestamp: record.timestamp,
        ...(record.id ? { record_id: record.id } : {}),
        value: this.editingRecord.value,
        note: this.editingRecord.note,
        ...(newTimestamp && newTimestamp !== record.timestamp ? { new_timestamp: newTimestamp } : {}),
      });

      this.expandedRecordId = null;
      this.editingRecord = null;
      await this._loadData();
    } catch (error) {
      console.error('Error updating record:', error);
      alert('Failed to update record: ' + error.message);
    }

    this.submitting = false;
    this._render();
  }

  _cancelRecordEdit() {
    this.expandedRecordId = null;
    this.editingRecord = null;
    this._render();
  }

  _showDeleteRecordConfirm(record) {
    this.deleteTarget = {
      type: 'record',
      id: this._generateRecordId(record),
      name: `${record.record_name || record.record_type} record`,
      record: record,
    };
    this.showDeleteConfirm = true;
    this._render();
  }

  // ============================================================================
  // Type Management (unified Record Types)
  // ============================================================================

  _openAddTypeDialog() {
    this.editingType = {
      mode: 'add',
      memberId: this.selectedMemberId || this.members[0]?.id || '',
      data: { name: '', unit: '', default_value: 0, default_value_mode: 'fixed' },
    };
    this.showTypeDialog = true;
    this._render();
  }

  _openEditTypeDialog(memberId, typeData) {
    this.editingType = {
      mode: 'edit',
      memberId: memberId,
      typeId: typeData.type,
      data: {
        name: typeData.name,
        unit: typeData.unit,
        default_value: typeData.default_value ?? 0,
        default_value_mode: typeData.default_value_mode || 'fixed',
      },
    };
    this.showTypeDialog = true;
    this._render();
  }

  _closeTypeDialog() {
    this.showTypeDialog = false;
    this.editingType = null;
    this._render();
  }

  async _saveType() {
    if (this.submitting || !this.editingType) return;
    this.submitting = true;
    this._render();

    try {
      const { mode, memberId, typeId, data } = this.editingType;

      if (mode === 'add') {
        await this._hass.callWS({
          type: 'woow_ha_records/health/add_record_type',
          member_id: memberId,
          name: data.name,
          unit: data.unit,
          default_value: data.default_value,
          default_value_mode: data.default_value_mode || 'fixed',
        });
      } else {
        await this._hass.callWS({
          type: 'woow_ha_records/health/update_record_type',
          member_id: memberId,
          type_id: typeId,
          name: data.name,
          unit: data.unit,
          default_value: data.default_value,
          default_value_mode: data.default_value_mode || 'fixed',
        });
      }

      this._closeTypeDialog();
      // Wait for integration reload to complete before fetching data
      await this._waitForReloadAndRefresh();
    } catch (error) {
      console.error('Error saving type:', error);
      alert('Failed to save type: ' + error.message);
    }

    this.submitting = false;
    this._render();
  }

  // Helper to wait for integration reload and refresh data
  async _waitForReloadAndRefresh() {
    // The backend reloads the config entry which takes some time
    // Save current URL and tab state before reload
    const currentTab = this.activeTab;
    const currentMemberCollapsed = this.settingsMemberCollapsed;
    const currentTypesCollapsed = this.settingsTypesCollapsed;
    const currentDataCollapsed = this.settingsDataCollapsed;
    const panelUrl = '/ha-health-record';

    // Wait a bit then try to reload data, with retries
    const maxRetries = 10;
    const retryDelay = 300; // ms

    for (let i = 0; i < maxRetries; i++) {
      await new Promise(resolve => setTimeout(resolve, retryDelay));

      // Check if we've been navigated away
      if (window.location.pathname !== panelUrl) {
        console.log('Navigated away during reload, returning to panel...');
        // Use history API to navigate back to the panel
        history.pushState(null, '', panelUrl);
        // Dispatch a popstate event to trigger HA's router
        window.dispatchEvent(new PopStateEvent('popstate', { state: null }));
        await new Promise(resolve => setTimeout(resolve, 500));
      }

      try {
        await this._loadData();
        // Restore tab and collapse state
        this.activeTab = currentTab;
        this.settingsMemberCollapsed = currentMemberCollapsed;
        this.settingsTypesCollapsed = currentTypesCollapsed;
        this.settingsDataCollapsed = currentDataCollapsed;
        this._render();
        return; // Success
      } catch (error) {
        console.log(`Retry ${i + 1}/${maxRetries} failed, waiting...`);
        if (i === maxRetries - 1) {
          console.error('Failed to reload data after integration reload:', error);
        }
      }
    }
  }

  _showDeleteTypeConfirm(memberId, typeData) {
    this.deleteTarget = {
      type: 'recordType',
      id: typeData.type,
      name: typeData.name,
      memberId: memberId,
    };
    this.showDeleteConfirm = true;
    this._render();
  }

  // ============================================================================
  // Member Management
  // ============================================================================

  _openAddMemberDialog() {
    this.editingMember = {
      mode: 'add',
      data: { name: '', member_id: '', note: '' },
    };
    this.showMemberDialog = true;
    this._render();
  }

  _openEditMemberDialog(member) {
    this.editingMember = {
      mode: 'edit',
      originalId: member.id,
      data: { name: member.name, member_id: member.id, note: member.note || '' },
    };
    this.showMemberDialog = true;
    this._render();
  }

  _closeMemberDialog() {
    this.showMemberDialog = false;
    this.editingMember = null;
    this._render();
  }

  async _saveMember() {
    if (this.submitting || !this.editingMember) return;
    this.submitting = true;
    this._render();

    try {
      const { mode, originalId, data } = this.editingMember;

      if (mode === 'add') {
        await this._hass.callWS({
          type: 'woow_ha_records/health/add_member',
          name: data.name,
          ...(data.member_id ? { member_id: data.member_id } : {}),
          ...(data.note ? { note: data.note } : {}),
        });
      } else {
        await this._hass.callWS({
          type: 'woow_ha_records/health/update_member',
          member_id: originalId,
          name: data.name,
          ...(data.note !== undefined ? { note: data.note } : {}),
        });
      }

      this._closeMemberDialog();
      // Wait for integration reload to complete before fetching data
      await this._waitForReloadAndRefresh();
    } catch (error) {
      console.error('Error saving member:', error);
      alert('Failed to save member: ' + error.message);
    }

    this.submitting = false;
    this._render();
  }

  _showDeleteMemberConfirm(member) {
    this.deleteTarget = {
      type: 'member',
      id: member.id,
      name: member.name,
    };
    this.showDeleteConfirm = true;
    this._render();
  }

  // ============================================================================
  // Delete Confirmation
  // ============================================================================

  _closeDeleteConfirm() {
    this.showDeleteConfirm = false;
    this.deleteTarget = null;
    this._render();
  }

  async _confirmDelete() {
    if (this.submitting || !this.deleteTarget) return;
    this.submitting = true;
    this._render();

    try {
      const { type, id, memberId, record } = this.deleteTarget;
      let needsReloadWait = false;

      switch (type) {
        case 'record':
          await this._hass.callWS({
            type: 'woow_ha_records/health/delete_record',
            member_id: record.member_id,
            type_id: record.record_type,
            timestamp: record.timestamp,
            ...(record.id ? { record_id: record.id } : {}),
          });
          break;
        case 'recordType':
          await this._hass.callWS({
            type: 'woow_ha_records/health/delete_record_type',
            member_id: memberId,
            type_id: id,
          });
          needsReloadWait = true;
          break;
        case 'member':
          await this._hass.callWS({
            type: 'woow_ha_records/health/delete_member',
            member_id: id,
          });
          needsReloadWait = true;
          // Reset selected member if deleted
          if (this.selectedMemberId === id) {
            this.selectedMemberId = '';
          }
          break;
      }

      this._closeDeleteConfirm();
      this.expandedRecordId = null;
      this.editingRecord = null;

      // Wait for integration reload if needed
      if (needsReloadWait) {
        await this._waitForReloadAndRefresh();
      } else {
        await this._loadData();
      }
    } catch (error) {
      console.error('Error deleting:', error);
      alert('Failed to delete: ' + error.message);
    }

    this.submitting = false;
    this._render();
  }

  // ============================================================================
  // Render
  // ============================================================================

  _render() {
    const styles = `
      :host {
        display: block;
        padding: 16px;
        background: var(--primary-background-color, #fafafa);
        min-height: 100vh;
        font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
      }
      *, *::before, *::after {
        box-sizing: border-box;
      }

      /* TOP BAR */
      .top-bar {
        display: flex;
        align-items: center;
        height: 56px;
        padding: 0 16px;
        background: var(--app-header-background-color, var(--primary-background-color));
        color: var(--app-header-text-color, var(--primary-text-color));
        border-bottom: 1px solid var(--divider-color);
        position: sticky;
        top: 0;
        z-index: 100;
        gap: 12px;
        margin: -16px -16px 16px -16px;
      }
      .top-bar-sidebar-btn {
        width: 40px;
        height: 40px;
        border: none;
        background: transparent;
        color: inherit;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        transition: background 0.2s;
        flex-shrink: 0;
      }
      .top-bar-sidebar-btn:hover { background: var(--secondary-background-color, rgba(0, 0, 0, 0.1)); }
      .top-bar-sidebar-btn svg { width: 24px; height: 24px; }
      .top-bar-title {
        flex: 1;
        font-size: 20px;
        font-weight: 500;
        margin: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        color: inherit;
      }
      .top-bar-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }

      /* SEARCH INPUT */
      .search-row-input-wrapper {
        flex: 1;
        display: flex;
        align-items: center;
        background: var(--card-background-color);
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        padding: 0 12px;
        height: 36px;
        transition: border-color 0.2s, box-shadow 0.2s;
      }
      .search-row-input-wrapper:focus-within {
        border-color: var(--primary-color);
        box-shadow: 0 0 0 2px rgba(var(--rgb-primary-color, 3, 169, 244), 0.2);
      }
      .search-row-icon {
        width: 20px;
        height: 20px;
        color: var(--secondary-text-color);
        flex-shrink: 0;
        margin-right: 8px;
      }
      .search-row-input {
        flex: 1;
        border: none;
        background: transparent;
        font-size: 14px;
        color: var(--primary-text-color);
        outline: none;
        height: 100%;
      }
      .search-row-input::placeholder { color: var(--secondary-text-color); }

      /* SEARCH ROW (full-width search input) */
      .search-row {
        padding: 0 16px 8px 16px;
        margin: 0 -16px 0 -16px;
      }
      .search-row .search-row-input-wrapper {
        width: 100%;
      }

      /* ACTION ROW (date range + add button) */
      .action-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 0 16px 16px 16px;
        margin: 0 -16px 0 -16px;
        flex-wrap: nowrap;
      }
      .action-row .date-range {
        display: flex;
        gap: 8px;
        align-items: center;
      }
      .action-row .date-separator {
        color: var(--secondary-text-color);
        flex-shrink: 0;
      }
      .action-row .add-record-btn {
        margin-left: auto;
      }
      .date-picker-wrapper {
        position: relative;
        display: inline-block;
      }
      .date-picker-trigger {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        padding: 8px 12px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
        cursor: pointer;
        font-size: 14px;
        min-width: 120px;
        transition: border-color 0.2s;
      }
      .date-picker-trigger:hover {
        border-color: var(--primary-color);
      }
      .date-picker-trigger .placeholder {
        color: var(--secondary-text-color);
      }
      .date-picker-trigger svg {
        flex-shrink: 0;
        color: var(--secondary-text-color);
      }
      .date-picker-clear {
        color: var(--secondary-text-color);
        cursor: pointer;
        font-size: 16px;
        padding: 0 2px;
        line-height: 1;
        flex-shrink: 0;
      }
      .date-picker-clear:hover {
        color: var(--error-color, #f44336);
      }
      .date-picker-dropdown {
        position: absolute;
        top: 100%;
        left: 0;
        z-index: 200;
        margin-top: 4px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        border-radius: 8px;
        background: var(--card-background-color, #fff);
      }
      .date-picker-dropdown .calendar-widget {
        min-width: 260px;
      }
      .calendar-widget {
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        padding: 12px;
        background: var(--card-background-color);
      }
      .calendar-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        font-weight: 500;
        font-size: 15px;
        color: var(--primary-text-color);
      }
      .calendar-header button {
        width: 32px;
        height: 32px;
        border: none;
        background: transparent;
        color: var(--primary-text-color);
        cursor: pointer;
        font-size: 18px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
      }
      .calendar-header button:hover {
        background: var(--secondary-background-color, rgba(0,0,0,0.05));
      }
      .calendar-weekdays {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        text-align: center;
        font-size: 12px;
        color: var(--secondary-text-color);
        font-weight: 500;
        margin-bottom: 4px;
      }
      .calendar-days {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 2px;
      }
      .calendar-day {
        aspect-ratio: 1;
        border: none;
        background: transparent;
        color: var(--primary-text-color);
        border-radius: 50%;
        cursor: pointer;
        font-size: 13px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
        padding: 0;
        min-width: 32px;
        min-height: 32px;
      }
      .calendar-day:hover {
        background: var(--secondary-background-color, rgba(0,0,0,0.05));
      }
      .calendar-day.selected {
        background: var(--primary-color);
        color: var(--text-primary-color, white);
        font-weight: 600;
      }
      .calendar-day.other-month {
        color: var(--disabled-text-color, #ccc);
        pointer-events: none;
      }

      /* MEMBER SWITCHER - Chip-style cards */
      .member-switcher-row {
        display: flex;
        align-items: center;
        padding: 0 16px 16px 16px;
        gap: 12px;
        flex-wrap: wrap;
        margin: 0 -16px;
      }
      .member-chip {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        background: var(--card-background-color);
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.2s;
        border: 2px solid transparent;
        box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,0.1));
        min-width: 140px;
      }
      .member-chip:hover {
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        transform: translateY(-2px);
      }
      .member-chip.active {
        border-color: var(--primary-color);
        background: var(--primary-color);
      }
      .member-chip.active .member-chip-name,
      .member-chip.active .member-chip-stat {
        color: var(--text-primary-color, white);
      }
      .member-chip-avatar {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--primary-color);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 18px;
        font-weight: 500;
        flex-shrink: 0;
      }
      .member-chip.active .member-chip-avatar {
        background: rgba(255,255,255,0.2);
      }
      .member-chip-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .member-chip-name {
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .member-chip-stat {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .member-chip-add {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 16px;
        background: transparent;
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.2s;
        border: 2px dashed var(--divider-color, #ccc);
        min-width: 120px;
        justify-content: center;
      }
      .member-chip-add:hover {
        border-color: var(--primary-color);
        background: var(--secondary-background-color, #f5f5f5);
      }
      .member-chip-add-icon {
        font-size: 20px;
        color: var(--secondary-text-color, #757575);
      }
      .member-chip-add-label {
        font-size: 14px;
        color: var(--secondary-text-color, #757575);
      }
      .member-chip-add:hover .member-chip-add-icon,
      .member-chip-add:hover .member-chip-add-label {
        color: var(--primary-color);
      }

      /* MEMBER OVERVIEW CARD */
      .overview-card {
        background: var(--card-background-color);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,0.1));
      }
      .overview-card-stat-label {
        font-size: 14px;
        color: var(--secondary-text-color);
        margin-bottom: 4px;
      }
      .overview-card-stat-primary {
        font-size: 32px;
        font-weight: bold;
        color: var(--primary-text-color);
      }
      .overview-card-details {
        font-size: 14px;
        color: var(--secondary-text-color);
        margin-top: 8px;
      }
      .overview-stats-row {
        display: flex;
        gap: 24px;
        margin-top: 12px;
        flex-wrap: wrap;
      }
      .overview-stat-item {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .overview-stat-value {
        font-size: 18px;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .overview-stat-label {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .overview-latest-section {
        border-top: 1px solid var(--divider-color, #e0e0e0);
        margin-top: 12px;
        padding-top: 10px;
      }
      .overview-latest-title {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--secondary-text-color);
        margin-bottom: 8px;
      }
      .overview-latest-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 6px 16px;
      }
      .overview-latest-item {
        display: inline-flex;
        align-items: baseline;
        gap: 4px;
      }
      .overview-latest-name {
        font-size: 13px;
        color: var(--secondary-text-color);
      }
      .overview-latest-value {
        font-size: 14px;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .overview-latest-unit {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .overview-latest-none {
        font-size: 14px;
        color: var(--disabled-text-color, #bdbdbd);
      }

      /* Tab Navigation */
      .tabs {
        display: flex;
        gap: 0;
        margin-bottom: 16px;
        border-bottom: 2px solid var(--divider-color, #e0e0e0);
      }
      .tab {
        padding: 12px 24px;
        background: transparent;
        border: none;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        color: var(--secondary-text-color, #757575);
        border-bottom: 2px solid transparent;
        margin-bottom: -2px;
        transition: color 0.2s, border-color 0.2s;
      }
      .tab:hover {
        color: var(--primary-text-color, #212121);
      }
      .tab.active {
        color: var(--primary-color, #03a9f4);
        border-bottom-color: var(--primary-color, #03a9f4);
      }

      /* Settings section headers */
      .settings-section-header {
        font-size: 14px;
        font-weight: 600;
        color: var(--primary-text-color, #212121);
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        user-select: none;
      }
      .settings-section-header:hover {
        color: var(--primary-color, #03a9f4);
      }
      .settings-section-header.collapsed {
        margin-bottom: 0;
        padding-bottom: 0;
        border-bottom: none;
      }
      .settings-section-header .chevron {
        font-size: 12px;
        transition: transform 0.2s;
      }
      .settings-section-header .chevron.collapsed {
        transform: rotate(-90deg);
      }
      .settings-section-content {
        overflow: hidden;
      }
      .settings-section-content.collapsed {
        display: none;
      }
      .settings-section-divider {
        height: 1px;
        background: var(--divider-color, #e0e0e0);
        margin: 20px 0;
      }

      .members-section {
        display: flex;
        gap: 16px;
        margin-bottom: 24px;
        flex-wrap: wrap;
      }
      .member-card {
        background: var(--card-background-color, white);
        border-radius: 12px;
        padding: 16px;
        min-width: 200px;
        box-shadow: 0 2px 2px rgba(0, 0, 0, 0.1);
      }
      .member-card h3 {
        margin: 0 0 12px 0;
        color: var(--primary-text-color, #212121);
        font-size: 18px;
      }
      .quick-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 12px;
      }
      .quick-filter-btn {
        padding: 6px 14px;
        background: var(--secondary-background-color, #e0e0e0);
        color: var(--primary-text-color, #212121);
        border: 2px solid transparent;
        border-radius: 16px;
        cursor: pointer;
        font-size: 12px;
        font-weight: 500;
        transition: background 0.2s, border-color 0.2s, color 0.2s;
      }
      .quick-filter-btn:hover {
        border-color: var(--primary-color);
      }
      .quick-filter-btn.active {
        background: var(--primary-color, #03a9f4);
        color: var(--text-primary-color, white);
        border-color: var(--primary-color, #03a9f4);
      }
      .add-record-btn {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        margin-left: auto;
        flex-shrink: 0;
      }
      .timeline-section {
        background: var(--card-background-color, white);
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 2px 2px rgba(0, 0, 0, 0.1);
      }
      .timeline-section h2 {
        margin: 0 0 16px 0;
        font-size: 18px;
        color: var(--primary-text-color, #212121);
      }
      .timeline-item {
        padding: 12px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        cursor: pointer;
        transition: background 0.2s;
      }
      .timeline-item:hover {
        background: var(--secondary-background-color, #f5f5f5);
      }
      .timeline-item:last-child {
        border-bottom: none;
      }
      .timeline-item.expanded {
        background: var(--secondary-background-color, #f5f5f5);
      }
      .timeline-row {
        display: flex;
        gap: 12px;
        align-items: flex-start;
      }
      .timeline-time {
        min-width: 90px;
        color: var(--secondary-text-color, #757575);
        font-size: 12px;
        line-height: 1.4;
        white-space: nowrap;
      }
      .timeline-content {
        flex: 1;
      }
      .timeline-header {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .timeline-type-tag {
        display: inline-block;
        background: var(--primary-color, #03a9f4);
        color: #fff;
        font-size: 11px;
        font-weight: 500;
        padding: 2px 8px;
        border-radius: 12px;
        line-height: 1.4;
      }
      .timeline-value {
        font-size: 16px;
        font-weight: 600;
        color: var(--primary-text-color, #212121);
      }
      .timeline-note {
        color: var(--secondary-text-color, #757575);
        font-size: 13px;
        font-style: italic;
        margin-top: 4px;
      }

      /* Expanded edit form */
      .timeline-edit-form {
        margin-top: 12px;
        padding: 12px;
        background: var(--card-background-color, white);
        border-radius: 8px;
        border: 1px solid var(--divider-color, #e0e0e0);
      }
      .edit-field {
        margin-bottom: 12px;
      }
      .edit-field label {
        display: block;
        margin-bottom: 4px;
        font-size: 12px;
        color: var(--secondary-text-color, #757575);
      }
      .edit-field input {
        width: 100%;
        padding: 8px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        box-sizing: border-box;
        background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      .edit-actions {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
      }
      .edit-actions-left {
        display: flex;
        gap: 8px;
      }

      /* Manage Tab Styles */
      .manage-section {
        background: var(--card-background-color, white);
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 2px 2px rgba(0, 0, 0, 0.1);
      }
      .type-card {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        margin-bottom: 8px;
      }
      .type-info {
        flex: 1;
      }
      .type-name {
        font-weight: 500;
        color: var(--primary-text-color, #212121);
      }
      .type-details {
        font-size: 13px;
        color: var(--secondary-text-color, #757575);
        margin-top: 4px;
      }
      .type-actions {
        display: flex;
        gap: 8px;
      }
      .member-label {
        font-size: 12px;
        color: var(--secondary-text-color, #757575);
        margin-bottom: 8px;
        padding-top: 16px;
      }
      .member-label:first-child {
        padding-top: 0;
      }
      .add-button {
        display: block;
        width: 100%;
        padding: 12px;
        margin-top: 16px;
        background: var(--primary-color, #03a9f4);
        color: white;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
      }
      .add-button:hover {
        opacity: 0.9;
      }

      /* Dialogs */
      .dialog-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
      }
      .dialog {
        background: var(--card-background-color, white);
        border-radius: 12px;
        padding: 24px;
        min-width: 320px;
        max-width: 90vw;
      }
      .dialog h3 {
        margin: 0 0 16px 0;
        color: var(--primary-text-color, #212121);
      }
      .dialog-field {
        margin-bottom: 16px;
      }
      .dialog-field label {
        display: block;
        margin-bottom: 4px;
        color: var(--secondary-text-color, #757575);
        font-size: 13px;
      }
      .dialog-field input, .dialog-field select, .dialog-field textarea {
        width: 100%;
        padding: 8px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        box-sizing: border-box;
        background: var(--card-background-color, white);
        color: var(--primary-text-color, #212121);
        font-family: inherit;
      }
      .dialog-field textarea {
        min-height: 60px;
        resize: vertical;
      }
      .dialog-actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 20px;
      }
      .btn {
        padding: 8px 16px;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 14px;
      }
      .btn-primary {
        background: var(--primary-color, #03a9f4);
        color: white;
      }
      .btn-secondary {
        background: var(--secondary-background-color, #e0e0e0);
        color: var(--primary-text-color, #212121);
      }
      .btn-danger {
        background: #f44336;
        color: white;
      }
      .btn-icon {
        padding: 6px 10px;
        background: transparent;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        cursor: pointer;
        font-size: 14px;
      }
      .btn-icon:hover {
        background: var(--secondary-background-color, #f5f5f5);
      }
      .btn-icon.danger {
        color: #f44336;
        border-color: #f44336;
      }
      .btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .loading {
        text-align: center;
        padding: 40px;
        color: var(--secondary-text-color, #757575);
      }
      .empty {
        text-align: center;
        padding: 40px;
        color: var(--secondary-text-color, #757575);
      }

      /* Delete Confirm Dialog */
      .delete-confirm-text {
        color: var(--primary-text-color, #212121);
        margin-bottom: 20px;
      }

      /* Timestamp row */
      .timestamp-row {
        display: flex;
        gap: 8px;
        align-items: center;
      }
      .timestamp-row input {
        flex: 1;
      }
      .btn-small {
        padding: 6px 12px;
        font-size: 12px;
      }

      /* Type records (records under type cards) */
      .type-records {
        margin-left: 16px;
        margin-bottom: 16px;
        border-left: 2px solid var(--divider-color, #e0e0e0);
        padding-left: 12px;
      }
      .record-item {
        padding: 8px;
        margin-bottom: 4px;
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 4px;
        cursor: pointer;
        transition: background 0.2s;
      }
      .record-item:hover {
        background: var(--divider-color, #e0e0e0);
      }
      .record-item.expanded {
        background: var(--card-background-color, white);
        border: 1px solid var(--divider-color, #e0e0e0);
      }
      .record-row {
        display: flex;
        gap: 12px;
        align-items: center;
        flex-wrap: wrap;
      }
      .record-time {
        font-size: 13px;
        color: var(--secondary-text-color, #757575);
        min-width: 120px;
      }
      .record-value {
        font-weight: 500;
        color: var(--primary-text-color, #212121);
      }
      .record-note {
        font-size: 13px;
        color: var(--secondary-text-color, #757575);
        font-style: italic;
      }

      /* Mobile responsive */
      @media (max-width: 600px) {
        :host {
          padding: 8px;
        }
        .top-bar {
          margin: -8px -8px 8px -8px;
        }
        .top-bar-sidebar-btn {
          width: 44px;
          height: 44px;
        }
        .top-bar-actions button {
          min-width: 44px;
          min-height: 44px;
        }
        .search-row {
          margin: 0 -8px 0 -8px;
          padding: 0 8px 8px 8px;
        }
        .action-row {
          margin: 0 -8px 0 -8px;
          padding: 0 8px 8px 8px;
          flex-wrap: wrap;
        }
        .search-row-input-wrapper {
          height: 44px;
        }
        .search-row-input {
          font-size: 16px;
        }
        .action-row .date-range {
          display: flex;
          gap: 8px;
          align-items: center;
          width: 100%;
          flex-shrink: 0;
        }
        .date-picker-wrapper {
          flex: 1;
          min-width: 0;
        }
        .date-picker-trigger {
          width: 100%;
          min-width: 0;
          font-size: 16px;
          padding: 8px 10px;
          min-height: 44px;
        }
        .date-picker-dropdown {
          position: fixed;
          left: 50%;
          top: 50%;
          transform: translate(-50%, -50%);
          right: auto;
          margin-top: 0;
          z-index: 300;
          max-height: 90vh;
          overflow-y: auto;
        }
        .action-row .date-separator {
          flex-shrink: 0;
        }
        .date-picker-clear {
          min-width: 44px;
          min-height: 44px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 20px;
          padding: 0;
        }
        .add-record-btn {
          width: 100%;
          margin-left: 0;
          flex-shrink: 1;
          min-height: 44px;
          justify-content: center;
        }
        .tab {
          min-height: 44px;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 8px 16px;
        }
        .quick-filter-btn {
          min-height: 44px;
          min-width: 44px;
          font-size: 13px;
          padding: 8px 14px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }
        .btn {
          min-height: 44px;
          padding: 10px 16px;
          font-size: 14px;
        }
        .btn-icon {
          min-height: 44px;
          min-width: 44px;
          padding: 8px 12px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }
        .dialog {
          width: 100%;
          max-width: 100%;
          height: 100vh;
          height: 100dvh;
          max-height: 100vh;
          max-height: 100dvh;
          border-radius: 0;
          overflow-y: auto;
          padding: 16px;
          padding-bottom: max(16px, env(safe-area-inset-bottom));
          box-sizing: border-box;
          display: flex;
          flex-direction: column;
        }
        .dialog-content {
          flex: 1;
          overflow-y: auto;
          -webkit-overflow-scrolling: touch;
        }
        .calendar-header button {
          width: 44px;
          height: 44px;
        }
        .calendar-day {
          min-width: 36px;
          min-height: 36px;
        }
        .settings-section-header {
          min-height: 44px;
          display: flex;
          align-items: center;
        }
        .dialog-field input,
        .dialog-field select,
        .dialog-field textarea {
          font-size: 16px;
          min-height: 44px;
        }
        .edit-field input,
        .edit-field select {
          font-size: 16px;
          min-height: 44px;
        }
        .member-switcher-row {
          padding: 0 8px 16px 8px;
          overflow-x: auto;
          flex-wrap: nowrap;
          -webkit-overflow-scrolling: touch;
          margin: 0 -8px;
        }
        .member-chip {
          min-width: 130px;
          flex-shrink: 0;
          padding: 10px 14px;
        }
        .member-chip-avatar {
          width: 36px;
          height: 36px;
          font-size: 16px;
        }
        .overview-card {
          padding: 12px;
        }
        .overview-card-stat-primary {
          font-size: 28px;
        }
        .overview-latest-grid {
          gap: 4px 12px;
        }
        .overview-latest-name {
          font-size: 12px;
        }
        .overview-latest-value {
          font-size: 13px;
        }
        .overview-latest-title {
          font-size: 12px;
        }
        .overview-latest-unit {
          font-size: 12px;
        }
      }
    `;

    let content = '';

    if (this.loading) {
      content = `<div class="loading">${this._t('loading')}</div>`;
    } else {
      // Top Bar (like Finance Record)
      content = `
        <div class="top-bar">
          <button class="top-bar-sidebar-btn" id="sidebar-toggle">
            <svg viewBox="0 0 24 24"><path fill="currentColor" d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"/></svg>
          </button>
          <h1 class="top-bar-title">${this._t('title')}</h1>
        </div>
      `;

      // Filter bar: Date Range + Search + Add Record (above member cards)
      {
        const selectedMember = this.members.find(m => m.id === this.selectedMemberId);
        const calendarSvg = '<svg width="16" height="16" viewBox="0 0 24 24"><path fill="currentColor" d="M19,19H5V8H19M16,1V3H8V1H6V3H5C3.89,3 3,3.89 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5C21,3.89 20.1,3 19,3H18V1M17,12H12V17H17V12Z"/></svg>';
        content += `
          <div class="search-row">
            <div class="search-row-input-wrapper">
              <svg class="search-row-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z"/></svg>
              <input
                class="search-row-input"
                type="text"
                id="search-input"
                placeholder="${this._t('search')}"
                value="${this._escapeHtml(this.searchQuery)}"
              />
            </div>
          </div>
          <div class="action-row">
            <div class="date-range">
              <div class="date-picker-wrapper" data-picker="start">
                <button type="button" class="date-picker-trigger" data-toggle-calendar="start">
                  <span class="${!this._filterDateStart ? 'placeholder' : ''}">
                    ${this._filterDateStart ? this._formatDateForInput(this._filterDateStart) : this._t('start_date')}
                  </span>
                  ${this._filterDateStart ? '<span class="date-picker-clear" data-clear-date="start">&times;</span>' : calendarSvg}
                </button>
                ${this._filterCalendarOpen === 'start' ? this._renderFilterCalendar('start') : ''}
              </div>
              <span class="date-separator">-</span>
              <div class="date-picker-wrapper" data-picker="end">
                <button type="button" class="date-picker-trigger" data-toggle-calendar="end">
                  <span class="${!this._filterDateEnd ? 'placeholder' : ''}">
                    ${this._filterDateEnd ? this._formatDateForInput(this._filterDateEnd) : this._t('end_date')}
                  </span>
                  ${this._filterDateEnd ? '<span class="date-picker-clear" data-clear-date="end">&times;</span>' : calendarSvg}
                </button>
                ${this._filterCalendarOpen === 'end' ? this._renderFilterCalendar('end') : ''}
              </div>
            </div>
            <button class="btn btn-primary add-record-btn" id="add-record-btn" ${!selectedMember ? 'disabled' : ''}>
              + ${this._t('addRecord')}
            </button>
          </div>
        `;
      }

      // Member Switcher Chips (always visible above tabs)
      if (this.members.length > 0) {
        content += this._renderMemberSwitcher();
        // Member Overview Card
        const selectedMemberOverview = this.members.find(m => m.id === this.selectedMemberId);
        if (selectedMemberOverview) {
          content += this._renderOverviewCard(selectedMemberOverview);
        }
      }

      // Tab Navigation
      content += `
        <div class="tabs">
          <button class="tab ${this.activeTab === 'record' ? 'active' : ''}" data-tab="record">${this._t('record')}</button>
          <button class="tab ${this.activeTab === 'settings' ? 'active' : ''}" data-tab="settings">${this._t('settings')}</button>
        </div>
      `;

      if (this.activeTab === 'record') {
        content += this._renderRecordTab();
      } else {
        content += this._renderSettingsTab();
      }
    }

    // Dialogs
    content += this._renderDialogs();

    this.shadowRoot.innerHTML = `<style>${styles}</style>${content}`;

    // Attach event listeners
    this._attachEventListeners();
  }

  _renderMemberSwitcher() {
    let html = '<div class="member-switcher-row">';
    for (const member of this.members) {
      const isActive = member.id === this.selectedMemberId;
      const initial = (member.name || '?').charAt(0).toUpperCase();
      const typeCount = (member.record_sets || []).length;
      html += `
        <div class="member-chip ${isActive ? 'active' : ''}" data-member-id="${member.id}">
          <div class="member-chip-avatar">${initial}</div>
          <div class="member-chip-info">
            <div class="member-chip-name">${this._escapeHtml(member.name)}</div>
            <div class="member-chip-stat">${typeCount} ${this._t('recordTypes')}</div>
          </div>
        </div>
      `;
    }
    html += `
      <div class="member-chip-add" id="add-member-chip">
        <span class="member-chip-add-icon">+</span>
        <span class="member-chip-add-label">${this._t('addMember')}</span>
      </div>
    `;
    html += '</div>';
    return html;
  }

  _renderOverviewCard(member) {
    // Count records for this member in current date range
    const memberRecords = this.records.filter(r => r.member_id === member.id);
    const totalCount = memberRecords.length;

    // Find last record
    let lastRecordInfo = this._t('noRecordsYet');
    if (memberRecords.length > 0) {
      const sorted = [...memberRecords].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      const last = sorted[0];
      const typeName = last.record_name || last.record_type || '';
      lastRecordInfo = `${this._formatDate(last.timestamp)} ${this._formatTime(last.timestamp)} - ${this._escapeHtml(typeName)}`;
    }

    const typeCount = (member.record_sets || []).length;

    // Build latest values section
    let latestValuesHtml = '';
    const recordSets = member.record_sets || [];
    if (recordSets.length > 0) {
      const items = recordSets.map(rs => {
        const name = this._escapeHtml(rs.name || rs.type || '');
        const hasValue = rs.current_value !== null && rs.current_value !== undefined;
        const valueHtml = hasValue
          ? `<span class="overview-latest-value">${this._escapeHtml(String(rs.current_value))}</span>${rs.unit ? ` <span class="overview-latest-unit">${this._escapeHtml(rs.unit)}</span>` : ''}`
          : '<span class="overview-latest-none">--</span>';
        return `<div class="overview-latest-item"><span class="overview-latest-name">${name}:</span> ${valueHtml}</div>`;
      }).join('');
      latestValuesHtml = `
        <div class="overview-latest-section">
          <div class="overview-latest-title">${this._t('latestValues')}</div>
          <div class="overview-latest-grid">${items}</div>
        </div>`;
    }

    return `
      <div class="overview-card">
        <div class="overview-card-stat-label">${this._t('totalRecords')}</div>
        <div class="overview-card-stat-primary">${totalCount}</div>
        <div class="overview-card-details">${this._t('lastRecord')}: ${lastRecordInfo}</div>
        <div class="overview-stats-row">
          <div class="overview-stat-item">
            <div class="overview-stat-value">${typeCount}</div>
            <div class="overview-stat-label">${this._t('recordTypesCount')}</div>
          </div>
        </div>
        ${latestValuesHtml}
      </div>
    `;
  }

  _renderRecordTab() {
    let html = '';

    // Lookup selected member early (needed for filter buttons)
    const selectedMember = this.members.find(m => m.id === this.selectedMemberId);

    // Record type filter buttons for selected member
    if (selectedMember) {
      const sets = selectedMember.record_sets || [];

      if (sets.length > 0) {
        html += `
          <div class="member-card" style="width: 100%; box-sizing: border-box;">
            <div class="quick-actions">
        `;

        for (const recordSet of sets) {
          const isActive = this.activeTypeFilters.includes(recordSet.type);
          html += `
            <button class="quick-filter-btn ${isActive ? 'active' : ''}" data-type="${recordSet.type}">
              ${this._escapeHtml(recordSet.name || recordSet.type)}
            </button>
          `;
        }

        html += '</div></div>';
      } else {
        html += `<div class="empty">${this._t('noRecordTypes')}</div>`;
      }
    } else if (this.members.length === 0) {
      html += `<div class="empty">${this._t('noMembers')}</div>`;
    }

    // Records timeline section (unified, no sub-tabs)
    const filteredRecords = this._getFilteredRecords();
    html += `<div class="timeline-section"><h2>${this._t('record')}</h2>`;
    if (filteredRecords.length === 0) {
      html += `<div class="empty">${this._t('noRecords')}</div>`;
    } else {
      for (const record of filteredRecords) {
        const recordId = this._generateRecordId(record);
        const isExpanded = this.expandedRecordId === recordId;
        const recordJson = JSON.stringify(record).replace(/'/g, "&#39;").replace(/"/g, '&quot;');

        html += `
          <div class="timeline-item ${isExpanded ? 'expanded' : ''}" data-record='${recordJson}'>
            <div class="timeline-row">
              <div class="timeline-time">${this._formatDateTime(record.timestamp)}</div>
              <div class="timeline-content">
                <div class="timeline-header">
                  <span class="timeline-type-tag">${this._escapeHtml(record.record_name || record.record_type)}</span>
                  <span class="timeline-value">${record.value != null ? record.value : ''} ${record.unit ? this._escapeHtml(record.unit) : ''}</span>
                </div>
                ${record.note ? `<div class="timeline-note">"${this._escapeHtml(record.note)}"</div>` : ''}
              </div>
            </div>
        `;

        if (isExpanded && this.editingRecord) {
          html += `
            <div class="timeline-edit-form">
              <div class="edit-field">
                <label>${this._t('timestamp')}</label>
                <div class="timestamp-row">
                  <input type="datetime-local" id="edit-timestamp" value="${this.editingRecord.timestamp}">
                  <button class="btn btn-secondary btn-small" id="edit-now-btn">${this._t('now')}</button>
                </div>
              </div>
              <div class="edit-field">
                <label>${this._t('value')}${record.unit ? ` (${record.unit})` : ''}</label>
                <input type="number" id="edit-value" value="${this.editingRecord.value}" step="0.1">
              </div>
              <div class="edit-field">
                <label>${this._t('note')}</label>
                <input type="text" id="edit-note" value="${this._escapeHtml(this.editingRecord.note)}" placeholder="${this._t('optionalNote')}">
              </div>
              <div class="edit-actions">
                <button class="btn-icon danger delete-record-btn" data-record='${recordJson}'>🗑 ${this._t('delete')}</button>
                <div class="edit-actions-left">
                  <button class="btn btn-secondary cancel-edit-btn">${this._t('cancel')}</button>
                  <button class="btn btn-primary save-edit-btn" data-record='${recordJson}' ${this.submitting ? 'disabled' : ''}>
                    ${this.submitting ? this._t('saving') : this._t('save')}
                  </button>
                </div>
              </div>
            </div>
          `;
        }

        html += '</div>';
      }
    }
    html += '</div>';

    return html;
  }

  _renderSettingsTab() {
    let html = '<div class="manage-section">';

    // Member Info section (collapsible)
    const memberCollapsed = this.settingsMemberCollapsed;
    html += `<div class="settings-section-header ${memberCollapsed ? 'collapsed' : ''}" data-toggle-section="member">
      ${this._t('memberInfoSection')}
      <span class="chevron ${memberCollapsed ? 'collapsed' : ''}">▼</span>
    </div>`;
    html += `<div class="settings-section-content ${memberCollapsed ? 'collapsed' : ''}">`;
    html += this._renderMembersManagement();
    html += '</div>';

    html += '<div class="settings-section-divider"></div>';

    // Record Types section (collapsible)
    const typesCollapsed = this.settingsTypesCollapsed;
    html += `<div class="settings-section-header ${typesCollapsed ? 'collapsed' : ''}" data-toggle-section="types">
      ${this._t('recordTypesSection')}
      <span class="chevron ${typesCollapsed ? 'collapsed' : ''}">▼</span>
    </div>`;
    html += `<div class="settings-section-content ${typesCollapsed ? 'collapsed' : ''}">`;
    html += this._renderRecordTypesManagement();
    html += '</div>';

    html += '<div class="settings-section-divider"></div>';

    // Data Management section (collapsible)
    const dataCollapsed = this.settingsDataCollapsed;
    html += `<div class="settings-section-header ${dataCollapsed ? 'collapsed' : ''}" data-toggle-section="data">
      ${this._t('dataManagementSection')}
      <span class="chevron ${dataCollapsed ? 'collapsed' : ''}">▼</span>
    </div>`;
    html += `<div class="settings-section-content ${dataCollapsed ? 'collapsed' : ''}">`;
    if (this.selectedMemberId && this.members.find(m => m.id === this.selectedMemberId)) {
      html += `<div style="padding: 12px 16px;">
        <button class="add-button" id="export-csv-btn">${this._t('exportCsv')}</button>
      </div>`;
    } else {
      html += `<div class="empty">${this._t('selectMember')}</div>`;
    }
    html += '</div>';

    html += '</div>';
    return html;
  }

  _renderRecordTypesManagement() {
    let html = '';

    const selectedMember = this.members.find(m => m.id === this.selectedMemberId);

    if (!selectedMember) {
      if (this.members.length === 0) {
        html += `<div class="empty">${this._t('noMembersManage')}</div>`;
      } else {
        html += `<div class="empty">${this._t('selectMember')}</div>`;
      }
    } else {
      const recordSets = selectedMember.record_sets || [];
      if (recordSets.length === 0) {
        html += `<div class="empty" style="padding: 16px;">${this._t('noRecordTypes')}</div>`;
      } else {
        for (const recordSet of recordSets) {
          const typeJson = JSON.stringify(recordSet).replace(/'/g, "&#39;").replace(/"/g, '&quot;');
          html += `
            <div class="type-card">
              <div class="type-info">
                <div class="type-name">${this._escapeHtml(recordSet.name)}</div>
                <div class="type-details">${this._t('unit')}: ${this._escapeHtml(recordSet.unit)} | ${this._t('defaultValue')}: ${recordSet.default_value_mode === 'last_value' ? this._t('lastValue') : (recordSet.default_value ?? 0)}</div>
              </div>
              <div class="type-actions">
                <button class="btn-icon edit-type-btn" data-member="${selectedMember.id}" data-type='${typeJson}'>✏️</button>
                <button class="btn-icon danger delete-type-btn" data-member="${selectedMember.id}" data-type='${typeJson}'>🗑</button>
              </div>
            </div>
          `;
        }
      }
      html += `<button class="add-button" id="add-record-type-btn">${this._t('addRecordType')}</button>`;
    }

    return html;
  }

  _renderMembersManagement() {
    let html = '';
    const member = this.members.find(m => m.id === this.selectedMemberId);

    if (!member) {
      html += `<div class="empty">${this._t('noMembersYet')}</div>`;
    } else {
      const memberJson = JSON.stringify(member).replace(/'/g, "&#39;").replace(/"/g, '&quot;');
      html += `
        <div class="type-card">
          <div class="type-info">
            <div class="type-name">${this._escapeHtml(member.name)}</div>
            <div class="type-details">
              ID: ${this._escapeHtml(member.id)} | ${this._t('recordTypes')}: ${(member.record_sets || []).length}
              ${member.note ? `<br>${this._t('note')}: ${this._escapeHtml(member.note)}` : ''}
            </div>
          </div>
          <div class="type-actions">
            <button class="btn-icon edit-member-btn" data-member='${memberJson}'>✏️</button>
            <button class="btn-icon danger delete-member-btn" data-member='${memberJson}'>🗑</button>
          </div>
        </div>
      `;
    }

    return html;
  }

  _renderDialogs() {
    let html = '';

    // Input Dialog (Quick Log - unified for all record types)
    if (this.showInputDialog && this.selectedMember) {
      const typeInfo = (this.selectedMember.record_sets || []).find(s => s.type === this.selectedType);
      const isAddMode = this.inputDialogMode === 'add';
      const dialogTitle = isAddMode
        ? this._t('addRecord')
        : this._t('logFor', { type: this._escapeHtml(typeInfo?.name || this.selectedType), name: this._escapeHtml(this.selectedMember.name) });

      // Build record type dropdown for add mode
      const allSets = this.selectedMember.record_sets || [];
      let typeSelectHtml = '';
      if (isAddMode) {
        typeSelectHtml = `
            <div class="dialog-field">
              <label>${this._t('recordType')}</label>
              <select id="input-type-select">
                ${allSets.map(s => `<option value="${s.type}" ${s.type === this.selectedType ? 'selected' : ''}>${this._escapeHtml(s.name || s.type)}</option>`).join('')}
              </select>
            </div>
        `;
      }

      html += `
        <div class="dialog-overlay" id="input-dialog-overlay">
          <div class="dialog">
            <h3>${dialogTitle}</h3>
            ${typeSelectHtml}
            <div class="dialog-field">
              <label>${this._t('timestamp')}</label>
              <div class="timestamp-row">
                <input type="datetime-local" id="input-timestamp" value="${this.inputTimestamp}">
                <button class="btn btn-secondary btn-small" id="input-now-btn">${this._t('now')}</button>
              </div>
            </div>
            <div class="dialog-field">
              <label>${this._t('value')}${typeInfo?.unit ? ` (${typeInfo.unit})` : ''}</label>
              <input type="number" id="input-value" value="${this.inputValue}" step="0.1">
            </div>
            <div class="dialog-field">
              <label>${this._t('note')}</label>
              <input type="text" id="input-note" placeholder="${this._t('optionalNote')}" value="${this._escapeHtml(this.inputNote)}">
            </div>
            <div class="dialog-actions">
              <button class="btn btn-secondary" id="cancel-input-btn">${this._t('cancel')}</button>
              <button class="btn btn-primary" id="save-input-btn" ${this.submitting ? 'disabled' : ''}>
                ${this.submitting ? this._t('saving') : this._t('save')}
              </button>
            </div>
          </div>
        </div>
      `;
    }

    // Type Dialog (Add/Edit Record Type - unified)
    if (this.showTypeDialog && this.editingType) {
      const isAdd = this.editingType.mode === 'add';
      const dialogTitle = isAdd ? this._t('addRecordTypeTitle') : this._t('editRecordTypeTitle');

      html += `
        <div class="dialog-overlay" id="type-dialog-overlay">
          <div class="dialog">
            <h3>${dialogTitle}</h3>
            <div class="dialog-field">
              <label>${this._t('name')}</label>
              <input type="text" id="type-name" value="${this._escapeHtml(this.editingType.data.name)}" placeholder="${this._t('namePlaceholder')}">
            </div>
            <div class="dialog-field">
              <label>${this._t('unit')}</label>
              <input type="text" id="type-unit" value="${this._escapeHtml(this.editingType.data.unit)}" placeholder="${this._t('unitPlaceholder')}">
            </div>
            <div class="dialog-field">
              <label>${this._t('defaultValueMode')}</label>
              <select id="type-default-mode">
                <option value="fixed" ${(this.editingType.data.default_value_mode || 'fixed') === 'fixed' ? 'selected' : ''}>${this._t('defaultValueFixed')}</option>
                <option value="last_value" ${this.editingType.data.default_value_mode === 'last_value' ? 'selected' : ''}>${this._t('defaultValueLastValue')}</option>
              </select>
            </div>
            ${(this.editingType.data.default_value_mode || 'fixed') === 'fixed' ? `
            <div class="dialog-field">
              <label>${this._t('defaultValue')}</label>
              <input type="number" id="type-default" value="${this.editingType.data.default_value}" step="0.1">
            </div>
            ` : ''}
            <div class="dialog-actions">
              <button class="btn btn-secondary" id="cancel-type-btn">${this._t('cancel')}</button>
              <button class="btn btn-primary" id="save-type-btn" ${this.submitting ? 'disabled' : ''}>
                ${this.submitting ? this._t('saving') : this._t('save')}
              </button>
            </div>
          </div>
        </div>
      `;
    }

    // Member Dialog (Add/Edit Member) - now with note field
    if (this.showMemberDialog && this.editingMember) {
      const isAdd = this.editingMember.mode === 'add';
      const dialogTitle = isAdd ? this._t('addMemberTitle') : this._t('editMemberTitle');

      html += `
        <div class="dialog-overlay" id="member-dialog-overlay">
          <div class="dialog">
            <h3>${dialogTitle}</h3>
            <div class="dialog-field">
              <label>${this._t('name')}</label>
              <input type="text" id="member-name" value="${this._escapeHtml(this.editingMember.data.name)}" placeholder="${this._t('memberNamePlaceholder')}">
            </div>
            ${isAdd ? `
              <div class="dialog-field">
                <label>${this._t('memberIdLabel')}</label>
                <input type="text" id="member-id" value="${this._escapeHtml(this.editingMember.data.member_id)}" placeholder="${this._t('memberIdPlaceholder')}">
              </div>
            ` : ''}
            <div class="dialog-field">
              <label>${this._t('memberNoteLabel')}</label>
              <textarea id="member-note" placeholder="${this._t('memberNotePlaceholder')}">${this._escapeHtml(this.editingMember.data.note || '')}</textarea>
            </div>
            <div class="dialog-actions">
              <button class="btn btn-secondary" id="cancel-member-btn">${this._t('cancel')}</button>
              <button class="btn btn-primary" id="save-member-btn" ${this.submitting ? 'disabled' : ''}>
                ${this.submitting ? this._t('saving') : this._t('save')}
              </button>
            </div>
          </div>
        </div>
      `;
    }

    // Delete Confirmation Dialog
    if (this.showDeleteConfirm && this.deleteTarget) {
      html += `
        <div class="dialog-overlay" id="delete-dialog-overlay">
          <div class="dialog">
            <h3>${this._t('confirmDelete')}</h3>
            <div class="delete-confirm-text">
              ${this._t('confirmDeleteMessage', { name: this._escapeHtml(this.deleteTarget.name) })}
            </div>
            <div class="dialog-actions">
              <button class="btn btn-secondary" id="cancel-delete-btn">${this._t('cancel')}</button>
              <button class="btn btn-danger" id="confirm-delete-btn" ${this.submitting ? 'disabled' : ''}>
                ${this.submitting ? this._t('deleting') : this._t('delete')}
              </button>
            </div>
          </div>
        </div>
      `;
    }

    return html;
  }

  _attachEventListeners() {
    // Sidebar toggle
    const sidebarBtn = this.shadowRoot.querySelector('#sidebar-toggle');
    if (sidebarBtn) sidebarBtn.addEventListener('click', () => this._toggleSidebar());

    // Tab navigation
    this.shadowRoot.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => this._switchTab(tab.dataset.tab));
    });

    // Settings section collapse/expand
    this.shadowRoot.querySelectorAll('[data-toggle-section]').forEach(header => {
      header.addEventListener('click', () => {
        const section = header.dataset.toggleSection;
        if (section === 'member') {
          this.settingsMemberCollapsed = !this.settingsMemberCollapsed;
        } else if (section === 'types') {
          this.settingsTypesCollapsed = !this.settingsTypesCollapsed;
        } else if (section === 'data') {
          this.settingsDataCollapsed = !this.settingsDataCollapsed;
        }
        this._render();
      });
    });

    // Calendar picker: toggle buttons
    this.shadowRoot.querySelectorAll('[data-toggle-calendar]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const which = btn.dataset.toggleCalendar; // 'start' or 'end'
        this._filterCalendarOpen = this._filterCalendarOpen === which ? '' : which;
        this._render();
      });
    });

    // Calendar picker: day selection
    this.shadowRoot.querySelectorAll('[data-calendar-day]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const day = parseInt(btn.dataset.calendarDay);
        this._filterCalendarSelectDay(day);
      });
    });

    // Calendar picker: prev/next month
    this.shadowRoot.querySelectorAll('[data-calendar-prev]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._filterCalendarPrev();
      });
    });
    this.shadowRoot.querySelectorAll('[data-calendar-next]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._filterCalendarNext();
      });
    });

    // Calendar picker: clear date
    this.shadowRoot.querySelectorAll('[data-clear-date]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const which = btn.dataset.clearDate;
        if (which === 'start') {
          this._filterDateStart = '';
        } else {
          this._filterDateEnd = '';
        }
        this._handleDateChange();
      });
    });

    // Calendar dropdown: prevent clicks inside from closing
    this.shadowRoot.querySelectorAll('[data-calendar-dropdown]').forEach(el => {
      el.addEventListener('click', (e) => e.stopPropagation());
    });

    // Search input
    const searchInput = this.shadowRoot.querySelector('#search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => this._onSearchInput(e));
    }

    // Member chip click handlers
    this.shadowRoot.querySelectorAll('.member-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const memberId = chip.dataset.memberId;
        if (memberId) {
          this.selectedMemberId = memberId;
          this.activeTypeFilters = [];
          this._render();
        }
      });
    });

    // Add Member chip in member switcher
    const addMemberChip = this.shadowRoot.querySelector('#add-member-chip');
    if (addMemberChip) {
      addMemberChip.addEventListener('click', () => this._openAddMemberDialog());
    }

    // Record type filter toggle buttons
    this.shadowRoot.querySelectorAll('.quick-filter-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const type = btn.getAttribute('data-type');
        if (type) {
          this._toggleTypeFilter(type);
        }
      });
    });

    // Add Record button
    const addRecordBtn = this.shadowRoot.querySelector('#add-record-btn');
    if (addRecordBtn) {
      addRecordBtn.addEventListener('click', () => this._openAddRecordDialog());
    }

    // Timeline item click (expand/collapse)
    this.shadowRoot.querySelectorAll('.timeline-item').forEach(item => {
      item.addEventListener('click', (e) => {
        // Don't toggle if clicking on form elements
        if (e.target.closest('.timeline-edit-form')) return;

        const recordData = item.getAttribute('data-record');
        if (recordData) {
          const record = JSON.parse(recordData.replace(/&quot;/g, '"'));
          this._toggleRecordExpand(record);
        }
      });
    });

    // Record item click in Record tab (expand/collapse)
    this.shadowRoot.querySelectorAll('.record-item').forEach(item => {
      item.addEventListener('click', (e) => {
        // Don't toggle if clicking on form elements
        if (e.target.closest('.timeline-edit-form')) return;

        const recordData = item.getAttribute('data-record');
        if (recordData) {
          const record = JSON.parse(recordData.replace(/&quot;/g, '"'));
          this._toggleRecordExpand(record);
        }
      });
    });

    // Edit form save button
    this.shadowRoot.querySelectorAll('.save-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const timestampInput = this.shadowRoot.querySelector('#edit-timestamp');
        const valueInput = this.shadowRoot.querySelector('#edit-value');
        const noteInput = this.shadowRoot.querySelector('#edit-note');
        if (timestampInput) this.editingRecord.timestamp = timestampInput.value;
        if (valueInput) this.editingRecord.value = parseFloat(valueInput.value) || 0;
        if (noteInput) this.editingRecord.note = noteInput.value;

        const recordData = btn.getAttribute('data-record');
        const record = JSON.parse(recordData.replace(/&quot;/g, '"'));
        this._saveRecordEdit(record);
      });
    });

    // Edit form "Now" button for timestamp
    const editNowBtn = this.shadowRoot.querySelector('#edit-now-btn');
    if (editNowBtn) {
      editNowBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const newTimestamp = this._toLocalISOString(new Date());
        this.editingRecord.timestamp = newTimestamp;
        const timestampInput = this.shadowRoot.querySelector('#edit-timestamp');
        if (timestampInput) timestampInput.value = newTimestamp;
      });
    }

    // Edit form cancel button
    this.shadowRoot.querySelectorAll('.cancel-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._cancelRecordEdit();
      });
    });

    // Delete record button
    this.shadowRoot.querySelectorAll('.delete-record-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const recordData = btn.getAttribute('data-record');
        const record = JSON.parse(recordData.replace(/&quot;/g, '"'));
        this._showDeleteRecordConfirm(record);
      });
    });

    // Export CSV button
    const exportCsvBtn = this.shadowRoot.querySelector('#export-csv-btn');
    if (exportCsvBtn) {
      exportCsvBtn.addEventListener('click', () => this._exportCsv());
    }

    // Type management - Edit buttons
    this.shadowRoot.querySelectorAll('.edit-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const memberId = btn.dataset.member;
        const typeData = JSON.parse(btn.dataset.type.replace(/&quot;/g, '"'));
        this._openEditTypeDialog(memberId, typeData);
      });
    });

    // Type management - Delete buttons
    this.shadowRoot.querySelectorAll('.delete-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const memberId = btn.dataset.member;
        const typeData = JSON.parse(btn.dataset.type.replace(/&quot;/g, '"'));
        this._showDeleteTypeConfirm(memberId, typeData);
      });
    });

    // Type management - Add button
    const addRecordTypeBtn = this.shadowRoot.querySelector('#add-record-type-btn');
    if (addRecordTypeBtn) {
      addRecordTypeBtn.addEventListener('click', () => {
        this._openAddTypeDialog();
      });
    }

    // Member management - Edit buttons
    this.shadowRoot.querySelectorAll('.edit-member-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const member = JSON.parse(btn.dataset.member.replace(/&quot;/g, '"'));
        this._openEditMemberDialog(member);
      });
    });

    // Member management - Delete buttons
    this.shadowRoot.querySelectorAll('.delete-member-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const member = JSON.parse(btn.dataset.member.replace(/&quot;/g, '"'));
        this._showDeleteMemberConfirm(member);
      });
    });

    // Input Dialog buttons
    const cancelInputBtn = this.shadowRoot.querySelector('#cancel-input-btn');
    if (cancelInputBtn) {
      cancelInputBtn.addEventListener('click', () => this._closeInputDialog());
    }

    const saveInputBtn = this.shadowRoot.querySelector('#save-input-btn');
    if (saveInputBtn) {
      saveInputBtn.addEventListener('click', () => {
        const timestampInput = this.shadowRoot.querySelector('#input-timestamp');
        const valueInput = this.shadowRoot.querySelector('#input-value');
        const noteInput = this.shadowRoot.querySelector('#input-note');
        if (timestampInput) this.inputTimestamp = timestampInput.value;
        if (valueInput) this.inputValue = parseFloat(valueInput.value) || 0;
        if (noteInput) this.inputNote = noteInput.value;
        this._submitInput();
      });
    }

    const inputNowBtn = this.shadowRoot.querySelector('#input-now-btn');
    if (inputNowBtn) {
      inputNowBtn.addEventListener('click', () => {
        this.inputTimestamp = this._toLocalISOString(new Date());
        const timestampInput = this.shadowRoot.querySelector('#input-timestamp');
        if (timestampInput) timestampInput.value = this.inputTimestamp;
      });
    }

    // Input dialog: record type dropdown change (add mode)
    const inputTypeSelect = this.shadowRoot.querySelector('#input-type-select');
    if (inputTypeSelect) {
      inputTypeSelect.addEventListener('change', () => {
        // Capture current timestamp and note before re-render
        const timestampInput = this.shadowRoot.querySelector('#input-timestamp');
        const noteInput = this.shadowRoot.querySelector('#input-note');
        if (timestampInput) this.inputTimestamp = timestampInput.value;
        if (noteInput) this.inputNote = noteInput.value;

        // Switch to the new type and update default value
        this.selectedType = inputTypeSelect.value;
        const typeInfo = (this.selectedMember.record_sets || []).find(s => s.type === this.selectedType);
        const useLastValue = typeInfo?.default_value_mode === 'last_value';
        this.inputValue = useLastValue
          ? (typeInfo?.current_value ?? typeInfo?.default_value ?? 0)
          : (typeInfo?.default_value ?? 0);
        this._render();
      });
    }

    const inputDialogOverlay = this.shadowRoot.querySelector('#input-dialog-overlay');
    if (inputDialogOverlay) {
      inputDialogOverlay.addEventListener('click', (e) => {
        if (e.target === inputDialogOverlay) this._closeInputDialog();
      });
    }

    // Type Dialog buttons
    const cancelTypeBtn = this.shadowRoot.querySelector('#cancel-type-btn');
    if (cancelTypeBtn) {
      cancelTypeBtn.addEventListener('click', () => this._closeTypeDialog());
    }

    const saveTypeBtn = this.shadowRoot.querySelector('#save-type-btn');
    if (saveTypeBtn) {
      saveTypeBtn.addEventListener('click', () => {
        const nameInput = this.shadowRoot.querySelector('#type-name');
        const unitInput = this.shadowRoot.querySelector('#type-unit');
        const defaultInput = this.shadowRoot.querySelector('#type-default');
        const modeSelect = this.shadowRoot.querySelector('#type-default-mode');

        if (nameInput) this.editingType.data.name = nameInput.value;
        if (unitInput) this.editingType.data.unit = unitInput.value;
        if (modeSelect) this.editingType.data.default_value_mode = modeSelect.value;
        if (defaultInput) this.editingType.data.default_value = parseFloat(defaultInput.value) || 0;

        this._saveType();
      });
    }

    // Type dialog: mode selector change (re-render to show/hide fixed value input)
    const typeDefaultMode = this.shadowRoot.querySelector('#type-default-mode');
    if (typeDefaultMode) {
      typeDefaultMode.addEventListener('change', () => {
        // Capture current form values before re-render
        const nameInput = this.shadowRoot.querySelector('#type-name');
        const unitInput = this.shadowRoot.querySelector('#type-unit');
        const defaultInput = this.shadowRoot.querySelector('#type-default');
        const memberSelect = this.shadowRoot.querySelector('#type-member');

        if (nameInput) this.editingType.data.name = nameInput.value;
        if (unitInput) this.editingType.data.unit = unitInput.value;
        if (defaultInput) this.editingType.data.default_value = parseFloat(defaultInput.value) || 0;
        if (memberSelect) this.editingType.memberId = memberSelect.value;
        this.editingType.data.default_value_mode = typeDefaultMode.value;
        this._render();
      });
    }

    const typeDialogOverlay = this.shadowRoot.querySelector('#type-dialog-overlay');
    if (typeDialogOverlay) {
      typeDialogOverlay.addEventListener('click', (e) => {
        if (e.target === typeDialogOverlay) this._closeTypeDialog();
      });
    }

    // Member Dialog buttons
    const cancelMemberBtn = this.shadowRoot.querySelector('#cancel-member-btn');
    if (cancelMemberBtn) {
      cancelMemberBtn.addEventListener('click', () => this._closeMemberDialog());
    }

    const saveMemberBtn = this.shadowRoot.querySelector('#save-member-btn');
    if (saveMemberBtn) {
      saveMemberBtn.addEventListener('click', () => {
        const nameInput = this.shadowRoot.querySelector('#member-name');
        const idInput = this.shadowRoot.querySelector('#member-id');
        const noteInput = this.shadowRoot.querySelector('#member-note');

        if (nameInput) this.editingMember.data.name = nameInput.value;
        if (idInput) this.editingMember.data.member_id = idInput.value;
        if (noteInput) this.editingMember.data.note = noteInput.value;

        this._saveMember();
      });
    }

    const memberDialogOverlay = this.shadowRoot.querySelector('#member-dialog-overlay');
    if (memberDialogOverlay) {
      memberDialogOverlay.addEventListener('click', (e) => {
        if (e.target === memberDialogOverlay) this._closeMemberDialog();
      });
    }

    // Delete Confirmation Dialog buttons
    const cancelDeleteBtn = this.shadowRoot.querySelector('#cancel-delete-btn');
    if (cancelDeleteBtn) {
      cancelDeleteBtn.addEventListener('click', () => this._closeDeleteConfirm());
    }

    const confirmDeleteBtn = this.shadowRoot.querySelector('#confirm-delete-btn');
    if (confirmDeleteBtn) {
      confirmDeleteBtn.addEventListener('click', () => this._confirmDelete());
    }

    const deleteDialogOverlay = this.shadowRoot.querySelector('#delete-dialog-overlay');
    if (deleteDialogOverlay) {
      deleteDialogOverlay.addEventListener('click', (e) => {
        if (e.target === deleteDialogOverlay) this._closeDeleteConfirm();
      });
    }
  }

  async _exportCsv() {
    if (!this.selectedMemberId) return;

    try {
      const result = await this._hass.callWS({
        type: 'woow_ha_records/health/export_csv',
        member_id: this.selectedMemberId,
      });

      if (!result.record_count) {
        alert(this._t('exportNoRecords'));
        return;
      }

      // Sanitize member name for filename: keep alphanumeric, CJK, spaces→underscore
      const safeName = result.member_name
        .replace(/[^\w\u4e00-\u9fff\u3400-\u4dbf\s-]/g, '')
        .replace(/\s+/g, '_');
      const dateStr = new Date().toISOString().slice(0, 10);
      const filename = `health_record_${safeName}_${dateStr}.csv`;

      // Prepend UTF-8 BOM for Excel CJK compatibility
      const bom = '\uFEFF';
      const blob = new Blob([bom + result.csv_content], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);

      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('CSV export failed:', error);
      alert('Export failed: ' + (error.message || error));
    }
  }

  _escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

customElements.define('ha-health-record-panel', HaHealthRecordPanel);
