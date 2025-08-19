// static/scripts/employee_detail.js
// ───────────────────────────────────────────────────────────
// 변경 요약
// - 탭 선택자를 '.tab[role="tab"]' 로 제한(이력서 아이콘 제외)
// - 섹션 토글 시 hidden 속성까지 동기화 (접근성/표시 모두 일치)
// - 초기에 모든 입력을 disabled 처리(이름 readonly 제외)
// ───────────────────────────────────────────────────────────
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('detail-form');
    if (!form) return;

    // ===== 유틸 =====
    function normalizeCommaNewlines(el) {
      let v = (el.value || '').replace(/\r\n/g, '\n');
      v = v.replace(/,\s*(?!\n)/g, ',\n').trim();   // 콤마 뒤 줄바꿈
      v = v.replace(/\n{3,}/g, '\n\n');            // 과도한 빈 줄 축소
      el.value = v;
    }
    function autoResize(el) {
      el.style.height = 'auto';
      el.style.overflow = 'hidden';
      el.style.height = (el.scrollHeight + 2) + 'px';
    }
    function resizeTextareasIn(sectionEl) {
      if (!sectionEl) return;
      const areas = sectionEl.querySelectorAll('textarea.auto-grow');
      areas.forEach((el) => autoResize(el));
    }

    // ===== 탭 전환 =====
    // PDF 아이콘은 role="button" 이라 제외됨
    const tabs = document.querySelectorAll('.tab[role="tab"]');
    const sections = document.querySelectorAll('.profile-section');

    function activateTab(tab) {
      const targetId = tab.dataset.target;

      tabs.forEach((t) => {
        const active = t === tab;
        t.classList.toggle('active', active);
        t.setAttribute('aria-selected', String(active));
      });

      sections.forEach((section) => {
        const active = section.id === targetId;
        section.classList.toggle('active', active);
        section.hidden = !active; // hidden 속성까지 동기화 ★
      });

      const targetSection = document.getElementById(targetId);
      requestAnimationFrame(() => resizeTextareasIn(targetSection));
    }

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => activateTab(tab));
      tab.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          e.preventDefault();
          const dir = e.key === 'ArrowRight' ? 1 : -1;
          const arr = Array.from(tabs);
          const idx = arr.indexOf(tab);
          const next = arr[(idx + dir + arr.length) % arr.length];
          next.focus();
          activateTab(next);
        }
      });
    });

    // 초기 탭 섹션 상태 보정(HTML에 hidden이 있을 수 있음)
    const initialActive = document.querySelector('.profile-section.active') || document.getElementById('basic-info');
    sections.forEach(sec => sec.hidden = !sec.classList.contains('active'));
    requestAnimationFrame(() => resizeTextareasIn(initialActive));

    // ===== 콤마→줄바꿈 + 자동 높이 =====
    const listAreas = form.querySelectorAll('textarea.auto-list');
    const growAreas = form.querySelectorAll('textarea.auto-grow');

    listAreas.forEach((el) => normalizeCommaNewlines(el));
    growAreas.forEach((el) => {
      el.addEventListener('input', () => autoResize(el));
    });
    listAreas.forEach((el) => {
      el.addEventListener('paste', () => {
        setTimeout(() => { normalizeCommaNewlines(el); autoResize(el); }, 0);
      });
      el.addEventListener('blur', () => {
        normalizeCommaNewlines(el);
        autoResize(el);
      });
    });

    // ===== 폼 편집/저장 토글 + 로딩 =====
    const inputs = form.querySelectorAll('input:not([readonly]), select, textarea');
    const editBtn = document.getElementById('edit-btn');
    const saveBtn = document.getElementById('save-btn');
    const loading = document.getElementById('loading');

    // 초기에 읽기 전용(비활성)
    inputs.forEach((el) => (el.disabled = true));

    let dirty = false;
    form.addEventListener('input', () => { if (!dirty) dirty = true; });

    if (editBtn) {
      editBtn.addEventListener('click', () => {
        const isDisabled = inputs[0] ? inputs[0].disabled : true;
        inputs.forEach((el) => (el.disabled = !isDisabled));
        if (isDisabled) {
          editBtn.textContent = '취소';
          if (saveBtn) saveBtn.style.display = 'inline-block';
          const visible = document.querySelector('.profile-section.active');
          requestAnimationFrame(() => resizeTextareasIn(visible));
        } else {
          dirty = false;
          editBtn.textContent = '수정';
          if (saveBtn) saveBtn.style.display = 'none';
        }
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        listAreas.forEach((el) => normalizeCommaNewlines(el));
        if (loading) loading.classList.add('active');
        form.requestSubmit ? form.requestSubmit() : form.submit();
      });
    }

    // (옵션) 편집 중 이탈 경고
    window.addEventListener('beforeunload', (e) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  });
})();
