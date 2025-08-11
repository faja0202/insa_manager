// static/scripts/employee_detail.js
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('detail-form');
    if (!form) return;

    // 유틸
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
    // ★ 특정 섹션 안의 auto-grow만 리사이즈
    function resizeTextareasIn(sectionEl) {
      if (!sectionEl) return;
      const areas = sectionEl.querySelectorAll('textarea.auto-grow');
      areas.forEach((el) => autoResize(el));
    }

    // 1) 탭 전환
    const tabs = document.querySelectorAll('.tab');
    const sections = document.querySelectorAll('.profile-section');

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const targetId = tab.dataset.target;

        tabs.forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');

        sections.forEach((section) => {
          section.classList.toggle('active', section.id === targetId);
        });

        // ★ 탭이 바뀐 다음 프레임에서 대상 섹션 리사이즈
        const targetSection = document.getElementById(targetId);
        requestAnimationFrame(() => resizeTextareasIn(targetSection));
      });
    });

    // 2) 콤마→줄바꿈 + 자동 높이
    const listAreas = form.querySelectorAll('textarea.auto-list');
    const growAreas = form.querySelectorAll('textarea.auto-grow');

    // 초기 정규화/리사이즈
    listAreas.forEach((el) => normalizeCommaNewlines(el));
    // 활성 섹션만 먼저 리사이즈 (숨김 섹션은 scrollHeight=0일 수 있음)
    const initialActive = document.querySelector('.profile-section.active');
    if (initialActive) {
      requestAnimationFrame(() => resizeTextareasIn(initialActive));
    }

    // 입력 중엔 높이만 반영
    growAreas.forEach((el) => {
      el.addEventListener('input', () => autoResize(el));
    });
    // 붙여넣기/포커스아웃 시 정규화 + 리사이즈
    listAreas.forEach((el) => {
      el.addEventListener('paste', () => {
        setTimeout(() => { normalizeCommaNewlines(el); autoResize(el); }, 0);
      });
      el.addEventListener('blur', () => {
        normalizeCommaNewlines(el);
        autoResize(el);
      });
    });

    // 3) 폼 편집/저장 토글 + 로딩
    const inputs = form.querySelectorAll('input:not([readonly]), select, textarea');
    const editBtn = document.getElementById('edit-btn');
    const saveBtn = document.getElementById('save-btn');
    const loading = document.getElementById('loading');

    inputs.forEach((el) => (el.disabled = true));

    if (editBtn) {
      editBtn.addEventListener('click', () => {
        const isDisabled = inputs[0] ? inputs[0].disabled : true;
        inputs.forEach((el) => (el.disabled = !isDisabled));
        if (isDisabled) {
          editBtn.textContent = '취소';
          if (saveBtn) saveBtn.style.display = 'inline-block';
          // 편집 모드 진입 시 현재 보이는 섹션만 리사이즈
          const visible = document.querySelector('.profile-section.active');
          requestAnimationFrame(() => resizeTextareasIn(visible));
        } else {
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
        setTimeout(() => form.submit(), 300);
      });
    }
  });
})();
