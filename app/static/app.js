// Submit image generation request
async function submitGeneration(event) {
    event.preventDefault();

    const form = event.target;
    const prompt = form.prompt.value.trim();
    const model = form.model.value;
    const btn = form.querySelector('button[type="submit"]');

    if (!prompt) return;

    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');

    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, model })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to submit generation');
        }

        refreshQueue();
    } catch (error) {
        alert('Error: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.removeAttribute('aria-busy');
    }
}

// Cancel a pending job
async function cancelJob(jobId) {
    try {
        const response = await fetch(`/api/queue/${jobId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to cancel job');
        }

        refreshQueue();
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Delete an image
async function deleteImage(imageId, event) {
    event.stopPropagation();

    if (!confirm('Are you sure you want to delete this image?')) {
        return;
    }

    try {
        const response = await fetch(`/api/images/${imageId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete image');
        }

        // Remove the image card from DOM
        const card = document.getElementById(`image-${imageId}`);
        if (card) {
            card.remove();
        }

        // Also refresh recent images if on main page
        if (document.getElementById('recentImages')) {
            refreshRecentImages();
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Refresh queue display (debounced to prevent flashing)
let refreshQueueTimeout = null;
let refreshQueuePending = false;

async function refreshQueue() {
    const queueList = document.getElementById('queueList');
    if (!queueList) return;

    // If a refresh is already pending, just mark that we need another one
    if (refreshQueueTimeout) {
        refreshQueuePending = true;
        return;
    }

    // Debounce: wait a short time before actually refreshing
    refreshQueueTimeout = setTimeout(async () => {
        try {
            const response = await fetch('/partials/queue');
            if (response.ok) {
                queueList.innerHTML = await response.text();
            }
        } catch (error) {
            console.error('Failed to refresh queue:', error);
        }

        refreshQueueTimeout = null;

        // If another refresh was requested while we were waiting, do it now
        if (refreshQueuePending) {
            refreshQueuePending = false;
            refreshQueue();
        }
    }, 100);
}

// Refresh recent images display
async function refreshRecentImages() {
    const recentImages = document.getElementById('recentImages');
    if (!recentImages) return;

    try {
        const response = await fetch('/partials/recent-images');
        if (response.ok) {
            recentImages.innerHTML = await response.text();
        }
    } catch (error) {
        console.error('Failed to refresh images:', error);
    }
}

// Open image modal
function openModal(imageSrc) {
    const modal = document.getElementById('imageModal');
    const modalImg = document.getElementById('modalImage');

    modal.classList.add('active');
    modalImg.src = imageSrc;
}

// Close image modal
function closeModal() {
    const modal = document.getElementById('imageModal');
    modal.classList.remove('active');
}

// Close modal on escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeModal();
    }
});

// Global SSE connection
let eventSource = null;

// Set up SSE for real-time updates
function setupSSE() {
    // Close existing connection if any
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }

    eventSource = new EventSource('/api/queue/stream');

    eventSource.addEventListener('status', function(e) {
        console.log('[SSE] status event received:', e.data);
        const data = JSON.parse(e.data);
        updateQueueFromData(data);
    });

    eventSource.addEventListener('job_added', function(e) {
        refreshQueue();
    });

    eventSource.addEventListener('job_started', function(e) {
        const data = JSON.parse(e.data);
        // Update job status in place if element exists, otherwise refresh
        const jobElement = document.getElementById(`job-${data.job?.id}`);
        if (jobElement) {
            const statusSpan = jobElement.querySelector('.status');
            if (statusSpan) {
                statusSpan.className = 'status status-processing processing-indicator';
                statusSpan.textContent = 'processing';
            }
            // Add progress bar if not present
            if (!jobElement.querySelector('.progress-container')) {
                const header = jobElement.querySelector('.queue-item-header');
                if (header) {
                    const progressHtml = `
                        <div class="progress-container">
                            <div class="progress-bar" id="progress-bar-${data.job.id}" style="width: 0%"></div>
                        </div>
                        <div class="progress-status" id="progress-status-${data.job.id}">Starting...</div>
                    `;
                    header.insertAdjacentHTML('afterend', progressHtml);
                }
            }
            // Remove cancel button
            const cancelBtn = jobElement.querySelector('button');
            if (cancelBtn) cancelBtn.remove();
        } else {
            refreshQueue();
        }
    });

    eventSource.addEventListener('job_completed', function(e) {
        refreshQueue();
        refreshRecentImages();
    });

    eventSource.addEventListener('job_failed', function(e) {
        refreshQueue();
    });

    eventSource.addEventListener('job_cancelled', function(e) {
        refreshQueue();
    });

    eventSource.addEventListener('job_progress', function(e) {
        const data = JSON.parse(e.data);
        updateJobProgress(data.job_id, data.progress, data.progress_status);
    });

    eventSource.onerror = function(e) {
        console.error('SSE error:', e);
        eventSource.close();
        eventSource = null;
        // Reconnect after a delay
        setTimeout(setupSSE, 5000);
    };

    return eventSource;
}

// Update queue from SSE data
function updateQueueFromData(data) {
    const queueList = document.getElementById('queueList');
    if (!queueList) return;

    if (!data.jobs || data.jobs.length === 0) {
        queueList.innerHTML = '<p class="empty-state">No jobs in queue</p>';
        return;
    }

    let html = '';
    for (const job of data.jobs) {
        const processingClass = job.status === 'processing' ? 'processing-indicator' : '';
        const cancelBtn = job.status === 'pending'
            ? `<button class="secondary outline" style="margin-left: 0.5rem; padding: 0.25rem 0.5rem; font-size: 0.75rem;" onclick="cancelJob('${job.id}')">Cancel</button>`
            : '';

        const progressSection = job.status === 'processing'
            ? `<div class="progress-container">
                   <div class="progress-bar" id="progress-bar-${job.id}" style="width: ${job.progress || 0}%"></div>
               </div>
               <div class="progress-status" id="progress-status-${job.id}">${escapeHtml(job.progress_status || 'Starting...')}</div>`
            : '';

        html += `
            <div class="queue-item" id="job-${job.id}">
                <div class="queue-item-header">
                    <span class="prompt" title="${escapeHtml(job.prompt)}">${escapeHtml(job.prompt)}</span>
                    <span class="status status-${job.status} ${processingClass}">${job.status}</span>
                    ${cancelBtn}
                </div>
                ${progressSection}
            </div>
        `;
    }
    queueList.innerHTML = html;
}

// Escape HTML for safe display
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Update job progress bar and status
function updateJobProgress(jobId, progress, status) {
    const progressBar = document.getElementById(`progress-bar-${jobId}`);
    const progressStatus = document.getElementById(`progress-status-${jobId}`);

    if (progressBar && progress >= 0) {
        progressBar.style.width = `${progress}%`;
    }

    if (progressStatus && status) {
        progressStatus.textContent = status;
    }
}

// Initialize SSE when on the main page
if (document.getElementById('queueList')) {
    setupSSE();
}
