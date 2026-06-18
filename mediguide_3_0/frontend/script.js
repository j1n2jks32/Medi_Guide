function startVoice(){

    const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

    if(!SpeechRecognition){
        alert("Voice recognition not supported. Use Chrome.");
        return;
    }

    const recognition = new SpeechRecognition();

    const lang = document.getElementById("voiceLang").value;

    recognition.lang = lang;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.start();

    alert("ðŸŽ¤ Listening... Speak your symptoms");

    recognition.onresult = function(event){

        const speech = event.results[0][0].transcript;

        document.getElementById("symptoms").value = speech;

    };

    recognition.onerror = function(event){
        alert("Voice error: " + event.error);
    };

}


function escapeHtml(text){
    return String(text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// -------------------------------
// Get Location
// -------------------------------
function getCurrentPositionPromise(options){
    return new Promise((resolve,reject)=>{
        navigator.geolocation.getCurrentPosition(resolve, reject, options);
    });
}

function sampleBestLocation(sampleMs = 8000){
    return new Promise((resolve,reject)=>{
        let best = null;
        let watchId = null;

        const stopAndResolve = ()=>{
            if (watchId !== null) {
                navigator.geolocation.clearWatch(watchId);
            }
            if (best) {
                resolve(best);
                return;
            }
            reject(new Error("No location samples collected"));
        };

        watchId = navigator.geolocation.watchPosition(
            (position)=>{
                const candidate = {
                    lat: position.coords.latitude,
                    lon: position.coords.longitude,
                    accuracy: Number(position.coords.accuracy || 0)
                };

                if (!best || candidate.accuracy < best.accuracy) {
                    best = candidate;
                }

                if (candidate.accuracy && candidate.accuracy <= 100) {
                    stopAndResolve();
                }
            },
            ()=>{},
            {
                enableHighAccuracy: true,
                timeout: 15000,
                maximumAge: 0
            }
        );

        setTimeout(stopAndResolve, sampleMs);
    });
}

async function getLocation(){

    if(!navigator.geolocation){
        throw new Error("Location not supported");
    }

    let quick = null;
    try {
        const pos = await getCurrentPositionPromise({
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0
        });
        quick = {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            accuracy: Number(pos.coords.accuracy || 0)
        };
    } catch (_err) {
        quick = null;
    }

    if (!quick || !quick.accuracy || quick.accuracy > 500) {
        try {
            const sampled = await sampleBestLocation(8000);
            if (!quick || sampled.accuracy < quick.accuracy) {
                return sampled;
            }
        } catch (_err2) {
            // Fallback to quick if sampling fails.
        }
    }

    if (quick) {
        return quick;
    }

    throw new Error("Could not detect location");
}


// -------------------------------
// Nearby Hospitals
// -------------------------------
async function loadHospitals(){

    try{

        const location = await getLocation();

        const response = await fetch("/nearby-hospitals",{

            method:"POST",
            headers:{
                "Content-Type":"application/json"
            },

            body: JSON.stringify(location)

        });

        let data = await response.json();
        const detectedAccuracy = Number(location?.accuracy || 0);

        if (detectedAccuracy > 5000) {
            const manualQuery = window.prompt(
                "Location accuracy is very low. Enter your city/area/pincode to find nearby hospitals:"
            );
            if (manualQuery && manualQuery.trim()) {
                const manualResponse = await fetch("/nearby-hospitals", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ location_query: manualQuery.trim() })
                });
                if (manualResponse.ok) {
                    data = await manualResponse.json();
                }
            }
        }

        const detectedLabel = data?.detected_location?.label || "";
        const detectedCoords = data?.coords
            ? `${Number(data.coords.lat).toFixed(4)}, ${Number(data.coords.lon).toFixed(4)}`
            : "";
        const responseAccuracy = Number(data?.coords?.accuracy_m || detectedAccuracy || 0);
        const accuracyText = responseAccuracy
            ? ` (accuracy approx ${Math.round(responseAccuracy)} m)`
            : "";
        const lowAccuracyNote = responseAccuracy > 5000
            ? `<div class="location-note">Low GPS accuracy detected. Enable device location/GPS and retry.</div>`
            : "";
        const sourceNote = data?.source === "manual"
            ? `<div class="location-note">Using manual location search.</div>`
            : "";

        let html = `
        <div class="hospital-box">
        <h3>ðŸ¥ Nearby Hospitals</h3>
        <div class="location-note">Detected location: ${escapeHtml(detectedLabel || detectedCoords || "Unavailable")}${escapeHtml(accuracyText)}</div>
        ${lowAccuracyNote}
        ${sourceNote}
        `;

        if (!data.hospitals || !data.hospitals.length) {
            html += `
            <div class="hospital-item">
                No hospitals found for detected coordinates.
            </div>
            `;
        }

        (data.hospitals || []).forEach(h=>{

            html += `
            <div class="hospital-item">
                ðŸ¥ <b>${escapeHtml(h.name)}</b><br>
                <a href="${escapeHtml(h.maps)}" target="_blank" rel="noopener noreferrer">
                ðŸ—º Open in Google Maps
                </a>
            </div>
            `;

        });

        html += `
        <br>
        <a href="tel:${data.ambulance}" class="ambulance-btn">
        ðŸš‘ Call Ambulance (${data.ambulance})
        </a>
        </div>
        `;

        return html;

    }catch(err){
        console.log(err);
        return `
        <div class="hospital-box">
            <h3>ðŸ¥ Nearby Hospitals</h3>
            <div class="hospital-item">
                Could not detect current location. Allow browser location permission and try again.
            </div>
        </div>
        `;
    }

}


// -------------------------------
// Main AI Function
// -------------------------------
async function getRecommendation(){

    const symptoms = document.getElementById("symptoms").value;

    const resultDiv = document.getElementById("result");

    if(!symptoms.trim()){
        resultDiv.innerHTML = "âŒ Enter symptoms";
        return;
    }

    resultDiv.innerHTML = `
    <div class="loading-box">
        <div class="spinner"></div>
        <div>
            <b>AI analyzing symptoms...</b>
        </div>
    </div>
    `;

    let reminderPhone = "";
    try {
        const storageKeys = ["mediguide_profile"];
        const authRes = await fetch("/auth-status");
        if (authRes.ok) {
            const authData = await authRes.json().catch(() => ({}));
            if (authData.authenticated && !authData.is_admin && authData.username) {
                storageKeys.unshift(`mediguide_profile_${authData.username}`);
            }
        }

        for (const key of storageKeys) {
            const raw = localStorage.getItem(key);
            if (!raw) continue;
            const savedProfile = JSON.parse(raw);
            const phone = String(savedProfile.phone || "").trim();
            if (phone) {
                reminderPhone = phone;
                break;
            }
        }
    } catch (_e) {
        reminderPhone = "";
    }

    const payload = { symptoms };
    if (reminderPhone) {
        payload.phone = reminderPhone;
    }

    const response = await fetch("/recommend",{

        method:"POST",
        headers:{
            "Content-Type":"application/json"
        },

        body: JSON.stringify(payload)

    });

    const data = await response.json();

    if(data.source === "EMERGENCY-PROTOCOL"){

        const hospitals = await loadHospitals();

        resultDiv.innerHTML = `
        <div class="emergency">
        ðŸš¨ MEDICAL EMERGENCY<br><br>
        ${data.advice}<br><br>
        ${hospitals}
        </div>
        `;

        return;
    }

    const hospitals = (data.severity === "MODERATE" || data.severity === "HIGH" || data.severity === "CRITICAL")
        ? await loadHospitals()
        : "";

    resultDiv.innerHTML = `
    <h3>Result</h3>

    <p><b>Disease:</b> ${data.disease}</p>

    <p><b>Medicine:</b> ${data.medicine}</p>

    <p><b>Advice:</b> ${data.advice}</p>

    <p><b>Severity:</b> ${data.severity}</p>

    ${hospitals}
    `;
}

