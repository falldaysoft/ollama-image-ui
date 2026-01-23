// Submit image generation request
async function submitGeneration(event) {
    event.preventDefault();

    const form = event.target;
    const prompt = form.prompt.value.trim();
    const model = form.model.value;
    const varyPrompt = form.vary_prompt?.checked || false;
    const btn = form.querySelector('button[type="submit"]');

    if (!prompt) return;

    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');

    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, model, vary_prompt: varyPrompt })
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

// Track current image index and list for navigation
let currentImageIndex = -1;
let currentImageList = [];

// Open image modal from element with data attributes
function openModalFromElement(imgElement) {
    const imageSrc = imgElement.src;
    const prompt = imgElement.dataset.prompt || '';
    const originalPrompt = imgElement.dataset.originalPrompt || null;

    // Find all images in the same grid for navigation
    const grid = imgElement.closest('.image-grid');
    if (grid) {
        currentImageList = Array.from(grid.querySelectorAll('.image-card img'));
        currentImageIndex = currentImageList.indexOf(imgElement);
    } else {
        currentImageList = [];
        currentImageIndex = -1;
    }

    openModal(imageSrc, prompt, originalPrompt);
}

// Open image modal
function openModal(imageSrc, prompt, originalPrompt) {
    const modal = document.getElementById('imageModal');
    const modalImg = document.getElementById('modalImage');
    const modalPrompts = document.getElementById('modalPrompts');

    modal.classList.add('active');
    modalImg.src = imageSrc;

    // Build prompt display
    let promptHtml = '';
    if (originalPrompt && originalPrompt.trim()) {
        // Show both original and varied prompts
        promptHtml = `
            <div class="prompt-section">
                <div class="prompt-label original">Original Prompt</div>
                <div class="prompt-text">${escapeHtml(originalPrompt)}</div>
            </div>
            <div class="prompt-section">
                <div class="prompt-label">Varied Prompt (used for generation)</div>
                <div class="prompt-text">${escapeHtml(prompt)}</div>
            </div>
        `;
    } else if (prompt) {
        // Just show the prompt
        promptHtml = `
            <div class="prompt-section">
                <div class="prompt-label">Prompt</div>
                <div class="prompt-text">${escapeHtml(prompt)}</div>
            </div>
        `;
    }
    modalPrompts.innerHTML = promptHtml;
}

// Close image modal
function closeModal() {
    const modal = document.getElementById('imageModal');
    modal.classList.remove('active');
    // Clear prompts
    const modalPrompts = document.getElementById('modalPrompts');
    if (modalPrompts) {
        modalPrompts.innerHTML = '';
    }
}

// Navigate to previous image in modal
function navigatePrevImage() {
    if (currentImageIndex > 0 && currentImageList.length > 0) {
        currentImageIndex--;
        const imgElement = currentImageList[currentImageIndex];
        const modalImg = document.getElementById('modalImage');
        const modalPrompts = document.getElementById('modalPrompts');

        modalImg.src = imgElement.src;

        const prompt = imgElement.dataset.prompt || '';
        const originalPrompt = imgElement.dataset.originalPrompt || null;
        updateModalPrompts(prompt, originalPrompt);
    }
}

// Navigate to next image in modal
function navigateNextImage() {
    if (currentImageIndex < currentImageList.length - 1 && currentImageList.length > 0) {
        currentImageIndex++;
        const imgElement = currentImageList[currentImageIndex];
        const modalImg = document.getElementById('modalImage');

        modalImg.src = imgElement.src;

        const prompt = imgElement.dataset.prompt || '';
        const originalPrompt = imgElement.dataset.originalPrompt || null;
        updateModalPrompts(prompt, originalPrompt);
    }
}

// Update modal prompts display
function updateModalPrompts(prompt, originalPrompt) {
    const modalPrompts = document.getElementById('modalPrompts');
    let promptHtml = '';
    if (originalPrompt && originalPrompt.trim()) {
        promptHtml = `
            <div class="prompt-section">
                <div class="prompt-label original">Original Prompt</div>
                <div class="prompt-text">${escapeHtml(originalPrompt)}</div>
            </div>
            <div class="prompt-section">
                <div class="prompt-label">Varied Prompt (used for generation)</div>
                <div class="prompt-text">${escapeHtml(prompt)}</div>
            </div>
        `;
    } else if (prompt) {
        promptHtml = `
            <div class="prompt-section">
                <div class="prompt-label">Prompt</div>
                <div class="prompt-text">${escapeHtml(prompt)}</div>
            </div>
        `;
    }
    modalPrompts.innerHTML = promptHtml;
}

// Handle keyboard navigation
document.addEventListener('keydown', function(event) {
    const modal = document.getElementById('imageModal');
    const isModalOpen = modal && modal.classList.contains('active');

    if (event.key === 'Escape') {
        closeModal();
    } else if (isModalOpen && event.key === 'ArrowLeft') {
        event.preventDefault();
        navigatePrevImage();
    } else if (isModalOpen && event.key === 'ArrowRight') {
        event.preventDefault();
        navigateNextImage();
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

        const varyBadge = job.vary_prompt
            ? `<span class="vary-badge" title="Prompt will be varied">vary</span>`
            : '';

        const variedPromptSection = job.varied_prompt
            ? `<div class="varied-prompt" title="${escapeHtml(job.varied_prompt)}">
                   <small><strong>Varied:</strong> ${escapeHtml(job.varied_prompt)}</small>
               </div>`
            : '';

        html += `
            <div class="queue-item" id="job-${job.id}">
                <div class="queue-item-header">
                    <span class="prompt" title="${escapeHtml(job.prompt)}">${escapeHtml(job.prompt)}</span>
                    ${varyBadge}
                    <span class="status status-${job.status} ${processingClass}">${job.status}</span>
                    ${cancelBtn}
                </div>
                ${variedPromptSection}
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
