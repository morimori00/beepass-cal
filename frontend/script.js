document.addEventListener('DOMContentLoaded', () => {
    // const API_BASE_URL = 'http://localhost:8000'; // FastAPIサーバーのアドレス
    const API_BASE_URL = location.href.slice(0,-1); 

    // DOM要素の取得
    const scheduleForm = document.getElementById('scheduleForm');
    const errorMessageDiv = document.getElementById('errorMessage');
    const calendarGrid = document.getElementById('calendarGrid');
    const currentMonthYearSpan = document.getElementById('currentMonthYear');
    const prevMonthBtn = document.getElementById('prevMonthBtn');
    const nextMonthBtn = document.getElementById('nextMonthBtn');
    const freeSlotsDisplay = document.getElementById('freeSlotsDisplay');
    const submitButton = document.getElementById('submitButton');
    const loader = document.getElementById('loader');
    const nameSelect = document.getElementById('nameSelect');
    const freeTextInputContainer = document.getElementById('freeTextInputContainer');
    const nameFreeText = document.getElementById('nameFreeText');

    // 削除モーダル関連のDOM要素
    const deleteModal = document.getElementById('deleteModal');
    const closeModalButton = document.getElementById('closeModalButton');
    const deleteModalDateText = document.getElementById('deleteModalDateText');
    const deleteNameSelect = document.getElementById('deleteNameSelect');
    const confirmDeleteButton = document.getElementById('confirmDeleteButton');
    const deleteLoader = document.getElementById('deleteLoader');
    const deleteModalErrorMessage = document.getElementById('deleteModalErrorMessage');
    // const findFreeSlotsButton = document.getElementById('findFreeSlotsButton');
    const memberCheckboxListContainer = document.getElementById('memberCheckboxListContainer');
    const freeSlotsLoader = document.getElementById('freeSlotsLoader');
    const durationMinutesInput = document.getElementById('durationMinutesInput');

    durationMinutesInput.addEventListener('change', function() {
        resetFreeSlots(); // 入力が変わったら空き時間を再検索
    }
    );

    let currentDate = new Date(); // 現在表示しているカレンダーの基準日
    let currentMonthEvents = []; // カレンダー表示中の月のイベントを保持（削除モーダルでのメンバーリスト生成用）
    let dateToDelete = null; // 削除対象の日付をモーダル用に保持

    const eventColors = [ // CSSで定義したクラス名に対応
        'event-color-0', 'event-color-1', 'event-color-2', 'event-color-3',
        'event-color-4', 'event-color-5', 'event-color-6', 'event-color-7'
    ];
    const memberColorMap = new Map(); // メンバー名と色クラスのマッピング
    let nextColorIndex = 0;

    function getMemberColorClass(memberName) {
        if (!memberColorMap.has(memberName)) {
            // 新しいメンバーの場合、次の色を割り当て
            memberColorMap.set(memberName, eventColors[nextColorIndex % eventColors.length]);
            nextColorIndex++;
            // もし定義した色数よりメンバーが多くなったら、デフォルト色を使うか、色を循環させる
            // 現在の実装は循環
        }
        return memberColorMap.get(memberName) || 'event-color-default'; // マップにない場合のフォールバック
    }

    // 月が変わった時などに色割り当てをリセットしたい場合は、この関数を呼び出す
    function resetMemberColorAssignments() {
        memberColorMap.clear();
        nextColorIndex = 0;
    }
    // --- ここまで色の管理 ---

    // --- 氏名ドロップダウンの変更イベントリスナー ---
    nameSelect.addEventListener('change', function() {
        if (this.value === 'free_text') {
            freeTextInputContainer.style.display = 'block';
            nameFreeText.required = true; // HTML5バリデーション用
            nameFreeText.focus();
        } else {
            freeTextInputContainer.style.display = 'none';
            nameFreeText.required = false;
            nameFreeText.value = ''; // クリア
        }
    });

    function populateMemberCheckboxes(events) {
        memberCheckboxListContainer.innerHTML = ''; // クリア
        const memberNames = [...new Set(events.map(event => event.name))].sort();

        if (memberNames.length === 0) {
            memberCheckboxListContainer.textContent = '表示月の予定にメンバーがいません。';
            // findFreeSlotsButton.disabled = true; // メンバーがいなければ検索不可
            return;
        }
        // findFreeSlotsButton.disabled = false;

        memberNames.forEach(name => {
            const label = document.createElement('label');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = name;
            checkbox.checked = true; // 初期状態は全員チェック
            checkbox.id = `member-${name.replace(/\s+/g, '-')}`; // ID用に空白などを置換

            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(name));
            memberCheckboxListContainer.appendChild(label);

            // チェックボックスの変更イベントリスナー
            checkbox.addEventListener('change', function() {
                resetFreeSlots(); // チェックボックスの状態が変わったら空き時間を再検索
            });
        });
    }

    

    // --- 削除モーダル制御関数 ---
    function openDeleteModal(dateStr, membersOnDate) {
        dateToDelete = dateStr;
        const [year, month, day] = dateStr.split('-');
        deleteModalDateText.textContent = `${year}年${parseInt(month, 10)}月${parseInt(day, 10)}日`;

        deleteNameSelect.innerHTML = '<option value="">メンバーを選択</option>'; // プルダウン初期化
        const uniqueMembers = [...new Set(membersOnDate)]; // 重複を削除

        if (uniqueMembers.length > 0) {
            uniqueMembers.sort().forEach(member => { // 名前順ソート
                const option = document.createElement('option');
                option.value = member;
                option.textContent = member;
                deleteNameSelect.appendChild(option);
            });
        } else {
            const option = document.createElement('option');
            option.value = "";
            option.textContent = "削除対象メンバーなし";
            option.disabled = true;
            deleteNameSelect.appendChild(option);
        }
        deleteModalErrorMessage.textContent = '';
        deleteModal.style.display = 'flex'; // flexで中央寄せ（CSS側で設定）
    }

    function closeDeleteModal() {
        deleteModal.style.display = 'none';
        dateToDelete = null;
        deleteNameSelect.value = ''; // プルダウンをリセット
        confirmDeleteButton.disabled = false;
        deleteLoader.style.display = 'none';
        deleteModalErrorMessage.textContent = '';
    }

    closeModalButton.addEventListener('click', closeDeleteModal);
    window.addEventListener('click', (event) => { // モーダル外クリックで閉じる
        if (event.target === deleteModal) {
            closeDeleteModal();
        }
    });

    // --- カレンダー描画とイベント取得 ---
    async function fetchAndDisplayCalendar(year, month) {
        currentMonthYearSpan.textContent = `${year}年 ${month}月`;
        calendarGrid.innerHTML = '';
        currentMonthEvents = []; // 月のイベントをリセット
        freeSlotsDisplay.innerHTML = 'メンバーを選択して「検索」ボタンを押してください。'; // 初期メッセージ

        const daysInMonth = new Date(year, month, 0).getDate();
        const firstDayOfMonthIndex = new Date(year, month - 1, 1).getDay();

        try {
            const response = await fetch(`${API_BASE_URL}/events/?year=${year}&month=${month}`);
            if (!response.ok) throw new Error(`イベント取得エラー: ${response.statusText}`);
            currentMonthEvents = await response.json();
            populateMemberCheckboxes(currentMonthEvents);
        } catch (error) {
            console.error('イベント取得失敗:', error);
            errorMessageDiv.textContent = error.message; // ページ上部のエラーメッセージ欄に表示
            populateMemberCheckboxes([]); 
        }

        let freeSlotsData = {};
        try {
            const response = await fetch(`${API_BASE_URL}/free_slots/?year=${year}&month=${month}`);
            if (!response.ok) throw new Error(`空き時間取得エラー: ${response.statusText}`);
            freeSlotsData = await response.json();
        } catch (error) {
            console.error('空き時間取得失敗:', error);
        }

        const dayHeaders = ['日', '月', '火', '水', '木', '金', '土'];
        dayHeaders.forEach(headerText => {
            const headerCell = document.createElement('div');
            headerCell.classList.add('calendar-day', 'day-header');
            headerCell.textContent = headerText;
            calendarGrid.appendChild(headerCell);
        });

        for (let i = 0; i < firstDayOfMonthIndex; i++) {
            const emptyCell = document.createElement('div');
            emptyCell.classList.add('calendar-day', 'empty');
            calendarGrid.appendChild(emptyCell);
        }

        for (let day = 1; day <= daysInMonth; day++) {
            const dayCell = document.createElement('div');
            dayCell.classList.add('calendar-day');
            const dateStr = `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
            dayCell.dataset.date = dateStr;

            const dateNumberContainer = document.createElement('div');
            dateNumberContainer.classList.add('date-number-container');

            const dateNumber = document.createElement('div');
            dateNumber.classList.add('date-number');
            dateNumber.textContent = day;
            dateNumberContainer.appendChild(dateNumber);

            const deleteDayButton = document.createElement('button');
            deleteDayButton.classList.add('delete-day-button');
            deleteDayButton.innerHTML = '×';
            deleteDayButton.title = `${day}日の予定をメンバー指定で削除`;
            deleteDayButton.addEventListener('click', (e) => {
                e.stopPropagation();
                const eventsOnThisDate = currentMonthEvents.filter(ev => ev.event_date === dateStr);
                const membersOnThisDate = eventsOnThisDate.map(ev => ev.name);
                openDeleteModal(dateStr, membersOnThisDate);
            });
            dateNumberContainer.appendChild(deleteDayButton);
            dayCell.appendChild(dateNumberContainer);

            const eventsList = document.createElement('ul');
            eventsList.classList.add('events-list');
            const todayEvents = currentMonthEvents.filter(event => event.event_date === dateStr);

            if (todayEvents.length > 0) {
                todayEvents.sort((a, b) => {
                    if (a.start_time < b.start_time) return -1;
                    if (a.start_time > b.start_time) return 1;
                    return 0;
                });
                todayEvents.forEach(event => {
                    const listItem = document.createElement('li');
                    const colorClass = getMemberColorClass(event.name);
                    listItem.classList.add(colorClass);
                    const startTimeFormatted = event.start_time.substring(0, 5);
                    const endTimeFormatted = event.end_time.substring(0, 5);
                    listItem.textContent = `${startTimeFormatted}-${endTimeFormatted} ${event.name}`;
                    eventsList.appendChild(listItem);
                });
            }
            dayCell.appendChild(eventsList);
            calendarGrid.appendChild(dayCell);
        }
        displayFreeSlotsForMonth(freeSlotsData, year, month);
    }
    // --- 空き時間検索ボタンのイベントリスナー ---
    async function resetFreeSlots() {
        const selectedMembers = [];
        memberCheckboxListContainer.querySelectorAll('input[type="checkbox"]:checked').forEach(checkbox => {
            selectedMembers.push(checkbox.value);
        });

        if (selectedMembers.length === 0) {
            freeSlotsDisplay.innerHTML = '検索するメンバーを1人以上選択してください。';
            return;
        }

        const durationMinutes = parseInt(durationMinutesInput.value, 10);
        if (isNaN(durationMinutes) || durationMinutes < 1) {
            freeSlotsDisplay.innerHTML = '<p class="error-message">最小持続時間は1以上の数値を入力してください。</p>';
            durationMinutesInput.focus();
            return;
        }

        freeSlotsDisplay.innerHTML = ''; // 前回の結果をクリア
        // findFreeSlotsButton.disabled = true;
        freeSlotsLoader.style.display = 'block';

        const year = currentDate.getFullYear();
        const month = currentDate.getMonth() + 1;
        
        // クエリパラメータを構築 (FastAPIは同じキーの複数パラメータをリストとして受け取る)
        const params = new URLSearchParams({ year, month, duration_minutes: durationMinutes });
        selectedMembers.forEach(member => params.append('members', member));

        try {
            const response = await fetch(`${API_BASE_URL}/free_slots/?${params.toString()}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(errorData?.detail || `空き時間取得エラー: ${response.statusText}`);
            }
            const freeSlotsData = await response.json();
            displayFreeSlotsForMonth(freeSlotsData, year, month); // 結果を表示
        } catch (error) {
            console.error('空き時間取得失敗:', error);
            freeSlotsDisplay.innerHTML = `<p class="error-message">空き時間の取得に失敗しました: ${error.message}</p>`;
        } finally {
            // findFreeSlotsButton.disabled = false;
            freeSlotsLoader.style.display = 'none';
        }
    };

    // --- 空き時間表示 ---
    function displayFreeSlotsForMonth(freeSlotsData, year, month) {
        freeSlotsDisplay.innerHTML = ''; // 表示をクリア
        let foundSlotsOverall = false;

        const sortedDates = Object.keys(freeSlotsData).sort(); // 日付文字列でソート

        if (sortedDates.length === 0) {
             freeSlotsDisplay.textContent = '選択されたメンバーの共通の空き時間はありませんでした。';
             return;
        }

        const dayOfWeekNames = ["日", "月", "火", "水", "木", "金", "土"]; // 曜日名の配列

        sortedDates.forEach(dateStr => { // dateStr は "YYYY-MM-DD"
            if (freeSlotsData[dateStr] && freeSlotsData[dateStr].length > 0) {
                foundSlotsOverall = true;

                // 日付文字列からDateオブジェクトを作成して曜日を取得
                // UTCとして解釈されるのを避けるため、ローカルタイムゾーンで日付を扱う
                // YYYY-MM-DD の形式は new Date() でローカルタイムとして解釈されることが多いが、
                // 確実にするため、またはタイムゾーン問題を避けるなら、日付部分のみ使う
                const dateParts = dateStr.split('-');
                const tempDate = new Date(parseInt(dateParts[0]), parseInt(dateParts[1]) - 1, parseInt(dateParts[2]));
                const dayOfWeek = dayOfWeekNames[tempDate.getDay()]; // getDay() は 0 (日曜) から 6 (土曜)

                const displayMonth = tempDate.getMonth() + 1;
                const displayDay = tempDate.getDate();

                const dayHeader = document.createElement('strong');
                // --- ★日付の横に曜日を追加★ ---
                dayHeader.textContent = `${displayMonth}/${displayDay} (${dayOfWeek}):`;
                // --- ここまで ---
                freeSlotsDisplay.appendChild(dayHeader);

                freeSlotsData[dateStr].forEach(slot => {
                    const slotDiv = document.createElement('div');
                    slotDiv.textContent = `  ${slot.start} - ${slot.end}`;
                    freeSlotsDisplay.appendChild(slotDiv);
                });
            }
        });

        if (!foundSlotsOverall) {
            freeSlotsDisplay.textContent = '選択されたメンバーの共通の空き時間はありませんでした。';
        }
    }

    // --- 予定登録フォーム送信処理 ---
    scheduleForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorMessageDiv.textContent = '';
        submitButton.disabled = true;
        loader.style.display = 'block';

        const formData = new FormData();
        let finalName = '';

        if (nameSelect.value === 'free_text') {
            finalName = nameFreeText.value.trim();
            if (!finalName) {
                errorMessageDiv.textContent = '氏名 (自由記述) を入力してください。';
                submitButton.disabled = false;
                loader.style.display = 'none';
                nameFreeText.focus();
                return;
            }
        } else if (nameSelect.value) {
            finalName = nameSelect.value;
        } else {
            errorMessageDiv.textContent = '氏名を選択してください。';
            submitButton.disabled = false;
            loader.style.display = 'none';
            nameSelect.focus();
            return;
        }
        formData.append('name', finalName);

        const scheduleText = document.getElementById('scheduleText').value;
        if (scheduleText) formData.append('schedule_text', scheduleText);
        const imageFiles = document.getElementById('scheduleImage').files; // FileListオブジェクト
        if (imageFiles.length > 0) {
            for (let i = 0; i < imageFiles.length; i++) {
                formData.append('images', imageFiles[i]); // ★キー名を "images" (複数形) に変更し、ループで追加
            }
        }

        const currentViewingYear = currentDate.getFullYear();
        const currentViewingMonth = currentDate.getMonth() + 1;
        formData.append('target_year', currentViewingYear);
        formData.append('target_month', currentViewingMonth);

        if (!scheduleText && imageFiles.length === 0) {
            errorMessageDiv.textContent = '予定テキストまたは画像を1つ以上入力/選択してください。';
            submitButton.disabled = false;
            loader.style.display = 'none';
            return;
        }

        try {
            const response = await fetch(`${API_BASE_URL}/schedule/`, {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(errorData.detail || `サーバーエラー: ${response.status}`);
            }
            alert('予定が登録されました！');
            scheduleForm.reset();
            freeTextInputContainer.style.display = 'none';
            nameFreeText.required = false;
            nameSelect.value = "";
            fetchAndDisplayCalendar(currentViewingYear, currentViewingMonth);
        } catch (error) {
            console.error('予定登録失敗:', error);
            errorMessageDiv.textContent = `登録に失敗しました: ${error.message}`;
        } finally {
            submitButton.disabled = false;
            loader.style.display = 'none';
        }
    });

    // --- 削除実行ボタンのイベントリスナー ---
    confirmDeleteButton.addEventListener('click', async () => {
        const selectedName = deleteNameSelect.value;
        if (!dateToDelete || !selectedName) {
            deleteModalErrorMessage.textContent = '削除する日付またはメンバーが選択されていません。';
            return;
        }

        deleteModalErrorMessage.textContent = '';
        confirmDeleteButton.disabled = true;
        deleteLoader.style.display = 'block';

        try {
            const response = await fetch(`${API_BASE_URL}/events/delete_by_date_name/`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ event_date: dateToDelete, name: selectedName }),
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(errorData.detail || `削除サーバーエラー: ${response.status}`);
            }
            const result = await response.json();
            alert(result.message || '予定が削除されました。');
            closeDeleteModal();
            fetchAndDisplayCalendar(currentDate.getFullYear(), currentDate.getMonth() + 1);
        } catch (error) {
            console.error('削除失敗:', error);
            deleteModalErrorMessage.textContent = `削除に失敗: ${error.message}`;
        } finally {
            confirmDeleteButton.disabled = false;
            deleteLoader.style.display = 'none';
        }
    });

    // --- ナビゲーションボタン ---
    prevMonthBtn.addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() - 1);
        fetchAndDisplayCalendar(currentDate.getFullYear(), currentDate.getMonth() + 1);
    });

    nextMonthBtn.addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() + 1);
        fetchAndDisplayCalendar(currentDate.getFullYear(), currentDate.getMonth() + 1);
    });

    // --- 初期表示 ---
    fetchAndDisplayCalendar(currentDate.getFullYear(), currentDate.getMonth() + 1);
});