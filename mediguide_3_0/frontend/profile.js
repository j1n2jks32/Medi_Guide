// User Profile Management
let userProfile = {
    name: '',
    phone: '',
    email: '',
    age: '',
    gender: '',
    medicines: []
};
let whatsappConfigWarningShown = false;
let currentUsername = '';

function profileStorageKey() {
    return currentUsername ? `mediguide_profile_${currentUsername}` : 'mediguide_profile';
}

function applyProfileObject(profileObj) {
    const source = (profileObj && typeof profileObj === 'object') ? profileObj : {};
    userProfile = {
        name: String(source.name || ''),
        phone: String(source.phone || ''),
        email: String(source.email || ''),
        age: String(source.age || ''),
        gender: String(source.gender || ''),
        medicines: Array.isArray(source.medicines) ? source.medicines : []
    };
}

function normalizeReminderTime(rawTime) {
    const value = String(rawTime || '').trim();
    if (!value) return '';

    const hhmm = value.match(/^(\d{1,2}):(\d{2})$/);
    if (hhmm) {
        const hours = String(Math.min(23, Math.max(0, Number(hhmm[1])))).padStart(2, '0');
        return `${hours}:${hhmm[2]}`;
    }

    const ampm = value.match(/^(\d{1,2}):(\d{2})\s*([AaPp][Mm])$/);
    if (ampm) {
        let h = Number(ampm[1]) % 12;
        if (ampm[3].toUpperCase() === 'PM') h += 12;
        return `${String(h).padStart(2, '0')}:${ampm[2]}`;
    }

    return value;
}

function upsertMedicine(medicineName, reminderTime, persist = true) {
    const name = String(medicineName || '').trim();
    const time = normalizeReminderTime(reminderTime);
    if (!name || !time) return false;

    const existing = userProfile.medicines.find(
        (med) => med.name.toLowerCase() === name.toLowerCase() && med.time === time
    );

    if (existing) {
        existing.enabled = true;
    } else {
        userProfile.medicines.push({
            id: Date.now(),
            name,
            time,
            enabled: true
        });
    }

    renderMedicines();
    if (persist) saveProfile();
    return true;
}

// Load profile from backend first, fallback to local storage
async function loadProfile() {
    try {
        const response = await fetch('/profile-data');
        const data = await response.json().catch(() => ({}));
        if (response.ok && data.success) {
            applyProfileObject(data.profile || {});
            localStorage.setItem(profileStorageKey(), JSON.stringify(userProfile));
            updateFormFields();
            renderMedicines();
            return;
        }
    } catch (_error) {
        // Fallback to local storage below.
    }

    const savedProfile = localStorage.getItem(profileStorageKey()) || localStorage.getItem('mediguide_profile');
    if (savedProfile) {
        try {
            applyProfileObject(JSON.parse(savedProfile));
        } catch (_e) {
            applyProfileObject({});
        }
    }
    updateFormFields();
    renderMedicines();
}

// Save profile to localStorage
function saveProfile() {
    localStorage.setItem(profileStorageKey(), JSON.stringify(userProfile));
    showSuccessMessage('Profile saved successfully!');
}

// Update form fields with profile data
function updateFormFields() {
    document.getElementById('userName').value = userProfile.name || '';
    document.getElementById('userPhone').value = userProfile.phone || '';
    document.getElementById('userEmail').value = userProfile.email || '';
    document.getElementById('userAge').value = userProfile.age || '';
    document.getElementById('userGender').value = userProfile.gender || '';
}

// Add new medicine reminder
function addMedicine() {
    const medicineName = document.getElementById('newMedicine').value.trim();
    const reminderTime = normalizeReminderTime(document.getElementById('reminderTime').value);
    
    if (!medicineName || !reminderTime) {
        alert('Please enter both medicine name and reminder time');
        return;
    }

    upsertMedicine(medicineName, reminderTime, true);
    
    // Clear input fields
    document.getElementById('newMedicine').value = '';
    document.getElementById('reminderTime').value = '';
}

// Remove medicine reminder
function removeMedicine(id) {
    userProfile.medicines = userProfile.medicines.filter(med => med.id !== id);
    renderMedicines();
    saveProfile();
}

// Toggle medicine reminder
function toggleMedicine(id) {
    const medicine = userProfile.medicines.find(med => med.id === id);
    if (medicine) {
        medicine.enabled = !medicine.enabled;
        renderMedicines();
        saveProfile();
    }
}

// Render medicines list
function renderMedicines() {
    const medicineList = document.getElementById('medicineList');
    
    if (userProfile.medicines.length === 0) {
        medicineList.innerHTML = '<p style="text-align: center; color: #666;">No medicines added yet. Add your first medicine reminder above.</p>';
        return;
    }
    
    medicineList.innerHTML = userProfile.medicines.map(medicine => `
        <div class="medicine-item">
            <div class="medicine-info">
                <div class="medicine-name">${medicine.name}</div>
                <small>Reminder: ${medicine.time}</small>
            </div>
            <div style="display: flex; gap: 8px;">
                <button class="add-btn" onclick="toggleMedicine(${medicine.id})" style="background: ${medicine.enabled ? '#28a745' : '#6c757d'};">
                    ${medicine.enabled ? '🔔 ON' : '🔕 OFF'}
                </button>
                <button class="delete-btn" onclick="removeMedicine(${medicine.id})">🗑️ Delete</button>
            </div>
        </div>
    `).join('');
}

// Show success message
function showSuccessMessage(message) {
    const successDiv = document.getElementById('successMessage');
    successDiv.textContent = message;
    successDiv.style.display = 'block';
    
    setTimeout(() => {
        successDiv.style.display = 'none';
    }, 3000);
}

async function ensureAuthenticatedUser() {
    try {
        const res = await fetch('/auth-status');
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.authenticated) {
            window.location.href = '/login?next=/dashboard';
            return false;
        }
        if (data.is_admin) {
            window.location.href = '/admin/dashboard';
            return false;
        }
        currentUsername = String(data.username || '').trim();
        const badge = document.getElementById('loggedInUser');
        if (badge && currentUsername) {
            badge.textContent = `Logged in as: ${currentUsername}`;
        }
        return true;
    } catch (_e) {
        window.location.href = '/login?next=/dashboard';
        return false;
    }
}

async function logoutUser() {
    try {
        await fetch('/auth/logout', { method: 'POST' });
    } catch (_e) {
        // Redirect regardless of request result.
    }
    window.location.href = '/login?next=/dashboard';
}

// Form submission handler
document.getElementById('profileForm').addEventListener('submit', function(e) {
    e.preventDefault();
    
    // Update profile data
    userProfile.name = document.getElementById('userName').value;
    userProfile.phone = document.getElementById('userPhone').value;
    userProfile.email = document.getElementById('userEmail').value;
    userProfile.age = document.getElementById('userAge').value;
    userProfile.gender = document.getElementById('userGender').value;
    
    // Validate phone number
    const phoneRegex = /^[+][0-9]{10,15}$/;
    if (!phoneRegex.test(userProfile.phone)) {
        alert('Please enter a valid phone number with country code (e.g., +1234567890)');
        return;
    }
    
    // Validate email
    const emailRegex = /^[^@\s]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(userProfile.email)) {
        alert('Please enter a valid email address (e.g., user@example.com)');
        return;
    }

    // Auto-add typed reminder fields even if user forgot to click "Add Reminder".
    const pendingMedicine = document.getElementById('newMedicine').value.trim();
    const pendingReminderTime = normalizeReminderTime(document.getElementById('reminderTime').value);
    if ((pendingMedicine && !pendingReminderTime) || (!pendingMedicine && pendingReminderTime)) {
        alert('Please fill both medicine name and reminder time, or clear both fields.');
        return;
    }
    if (pendingMedicine && pendingReminderTime) {
        upsertMedicine(pendingMedicine, pendingReminderTime, false);
        document.getElementById('newMedicine').value = '';
        document.getElementById('reminderTime').value = '';
    }
    
    // Save profile
    saveProfile();
    
    // Send profile data to backend for storage
    sendProfileToBackend();
});

// Send profile to backend
function sendProfileToBackend() {
    fetch('/save-profile', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(userProfile)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('Profile saved to backend:', data);
        } else {
                if (String(data.error || '').toLowerCase().includes('login')) {
                window.location.href = '/login?next=/dashboard';
                return;
            }
            console.error('Error saving profile:', data.error);
        }
    })
    .catch(error => {
        console.error('Network error:', error);
    });
}

// Setup medicine reminders (check every minute)
function setupReminders() {
    setInterval(() => {
        const now = new Date();
        const currentTime = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
        
        userProfile.medicines.forEach(medicine => {
            if (medicine.enabled && medicine.time === currentTime) {
                // In a real app, this would send notification
                console.log(`Medicine reminder: ${medicine.name} at ${currentTime}`);
                
                // Show browser notification
                if ('Notification' in window && Notification.permission === 'granted') {
                    new Notification('MediGuide Reminder', {
                        body: `Time to take ${medicine.name}`,
                        icon: '/logo.svg'
                    });
                }
            }
        });
    }, 60000); // Check every minute
}

// Request notification permission
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

// Send WhatsApp reminder (backend integration)
function sendWhatsAppReminder(phoneNumber, medicineName) {
    fetch('/send-medicine-reminder', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            phone: phoneNumber,
            medicine: medicineName,
            message: `MediGuide Reminder: Time to take ${medicineName}. Please take your medicine as prescribed.`
        })
    })
    .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            throw new Error(data.error || `WhatsApp request failed (${response.status})`);
        }
        console.log('WhatsApp reminder sent:', data);
        return data;
    })
    .catch(error => {
        console.error('WhatsApp network error:', error);
        if (!whatsappConfigWarningShown) {
            alert(`WhatsApp reminder could not be sent: ${error.message}`);
            whatsappConfigWarningShown = true;
        }
    });
}

function sendTestWhatsAppNow() {
    const phoneNumber = document.getElementById('userPhone').value.trim();
    const phoneRegex = /^[+][0-9]{10,15}$/;
    if (!phoneRegex.test(phoneNumber)) {
        alert('Enter valid phone number first (e.g., +919876543210).');
        return;
    }

    const medicineName = (
        userProfile.medicines.find((m) => m.enabled)?.name ||
        document.getElementById('newMedicine').value.trim() ||
        'your medicine'
    );

    fetch('/send-medicine-reminder', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            phone: phoneNumber,
            medicine: medicineName,
            message: `MediGuide Test WhatsApp reminder for ${medicineName}.`
        })
    })
    .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            throw new Error(data.error || `WhatsApp request failed (${response.status})`);
        }
        showSuccessMessage('Test WhatsApp message sent successfully.');
        return data;
    })
    .catch((error) => {
        alert(`Test WhatsApp message failed: ${error.message}`);
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async function() {
    const authOk = await ensureAuthenticatedUser();
    if (!authOk) return;

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logoutUser);
    }

    await loadProfile();
    requestNotificationPermission();
    setupReminders();
});
