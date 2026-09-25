// Submit image generation request
async function submitGeneration(event) {
    event.preventDefault();

    const form = event.target;
    const prompt = form.prompt.value.trim();
    const model = form.model.value;
    const varyMode = form.vary_mode?.value || null;
    const count = parseInt(document.getElementById('count')?.value, 10) || 1;
    const width = form.width?.value ? parseInt(form.width.value, 10) : null;
    const height = form.height?.value ? parseInt(form.height.value, 10) : null;
    const seed = form.seed?.value !== '' && form.seed?.value != null ? parseInt(form.seed.value, 10) : null;
    const steps = form.steps?.value ? parseInt(form.steps.value, 10) : null;
    const btn = form.querySelector('button[type="submit"]');

    if (!prompt) return;

    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');

    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt, model, vary_mode: varyMode || null, count, width, height, seed, steps,
                reference_image: referenceImage?.filename || null
            })
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

// Cancel all pending jobs
async function cancelAllJobs() {
    try {
        const response = await fetch('/api/queue/cancel-all', {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to cancel all jobs');
        }

        const result = await response.json();
        console.log(`Cancelled ${result.count} job(s)`);
        refreshQueue();
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Delete an image
async function deleteImage(imageId, event) {
    if (event) {
        event.stopPropagation();
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

        // Refresh gallery sidebar
        refreshRecentImages();
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Delete current image in viewer
async function deleteCurrentImage() {
    if (!currentImageId) return;

    const imageId = currentImageId;

    // Navigate to next image before deleting
    const galleryImages = document.getElementById('galleryImages');
    if (galleryImages) {
        const images = galleryImages.querySelectorAll('.image-card img');
        if (images.length > 1) {
            // Move to next image (or previous if at end)
            const nextIndex = currentGalleryIndex < images.length - 1 ? currentGalleryIndex : currentGalleryIndex - 1;
            if (nextIndex >= 0 && images[nextIndex]) {
                displayImageInViewer(images[nextIndex]);
            }
        } else {
            // Last image, clear viewer
            const imageViewer = document.getElementById('imageViewer');
            const imageViewerInfo = document.getElementById('imageViewerInfo');
            if (imageViewer) {
                imageViewer.innerHTML = '<div class="image-viewer-placeholder">Select an image from the gallery or generate a new one</div>';
            }
            if (imageViewerInfo) {
                imageViewerInfo.style.display = 'none';
            }
            currentImageId = null;
            currentImageMetadata = null;
        }
    }

    // Delete the image
    await deleteImage(imageId, null);
}

// Reuse prompt from current image
function reusePrompt() {
    if (!currentImageMetadata) return;

    // Use original prompt if available, otherwise use the (possibly varied) prompt
    const promptToUse = currentImageMetadata.originalPrompt || currentImageMetadata.prompt;

    // Store in sessionStorage for cross-page access
    sessionStorage.setItem('reusePrompt', promptToUse);

    // If we're on the queue page, navigate to generate page
    if (window.location.pathname === '/queue') {
        window.location.href = '/';
        return;
    }

    const promptField = document.getElementById('prompt');
    if (promptField) {
        promptField.value = promptToUse;
        saveFormState();
        // Focus the prompt field and scroll to it
        promptField.focus();
        promptField.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// Reuse all parameters from current image
function reuseAll() {
    if (!currentImageMetadata) return;

    // Use original prompt if available, otherwise use the (possibly varied) prompt
    const params = {
        prompt: currentImageMetadata.originalPrompt || currentImageMetadata.prompt,
        model: currentImageMetadata.model,
        width: currentImageMetadata.width || '',
        height: currentImageMetadata.height || '',
        seed: currentImageMetadata.seed,
        steps: currentImageMetadata.steps,
        reference: currentImageMetadata.reference
    };

    // If we're not on the generate page, hand the parameters over via sessionStorage
    if (!document.getElementById('generateForm')) {
        sessionStorage.setItem('reuseAll', JSON.stringify(params));
        window.location.href = '/';
        return;
    }

    applyFormParams(params);
}

// Fill the generation form with previously used parameters
function applyFormParams(data) {
    const promptField = document.getElementById('prompt');
    const modelField = document.getElementById('model');
    const widthField = document.getElementById('width');
    const heightField = document.getElementById('height');
    const varyModeField = document.getElementById('varyMode');
    const seedField = document.getElementById('seed');
    const stepsField = document.getElementById('steps');

    if (promptField && data.prompt) {
        promptField.value = data.prompt;
    }

    // Set the reference first: it decides which models are selectable
    if (data.reference) {
        setReference({ filename: data.reference, url: `/uploads/${data.reference}` });
    } else {
        clearReference();
    }

    if (modelField && data.model) {
        modelField.value = data.model;
    }

    if (widthField) {
        widthField.value = data.width || '';
    }

    if (heightField) {
        heightField.value = data.height || '';
    }

    if (seedField) {
        seedField.value = data.seed ?? '';
    }

    if (stepsField && data.steps) {
        stepsField.value = data.steps;
    }

    // Reset vary mode to None since we're reusing an already-generated image
    if (varyModeField) {
        varyModeField.value = '';
    }

    updateModelOptions();
    saveFormState();

    // Focus the prompt field and scroll to it
    if (promptField) {
        promptField.focus();
        promptField.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// ============ Reference image (edits) ============

// Currently attached reference: { filename, url } or null
let referenceImage = null;

function setReference(ref) {
    referenceImage = ref;
    const preview = document.getElementById('referencePreview');
    const previewWrap = document.getElementById('referencePreviewWrap');
    const empty = document.getElementById('referenceEmpty');
    const hint = document.getElementById('editHint');
    if (preview) preview.src = ref.url;
    if (previewWrap) previewWrap.hidden = false;
    if (empty) empty.hidden = true;
    if (hint) hint.hidden = false;
    updateModelOptions();
    saveFormState();
}

function clearReference(event) {
    if (event) {
        event.stopPropagation();
    }
    referenceImage = null;
    const preview = document.getElementById('referencePreview');
    const previewWrap = document.getElementById('referencePreviewWrap');
    const empty = document.getElementById('referenceEmpty');
    const hint = document.getElementById('editHint');
    const fileInput = document.getElementById('referenceFile');
    if (preview) preview.removeAttribute('src');
    if (previewWrap) previewWrap.hidden = true;
    if (empty) empty.hidden = false;
    if (hint) hint.hidden = true;
    if (fileInput) fileInput.value = '';
    updateModelOptions();
    saveFormState();
}

async function uploadReference(file) {
    if (!file || !file.type.startsWith('image/')) {
        alert('Please choose an image file');
        return;
    }

    const drop = document.getElementById('referenceDrop');
    drop?.setAttribute('aria-busy', 'true');

    try {
        const formData = new FormData();
        formData.append('file', file);
        const response = await fetch('/api/references', { method: 'POST', body: formData });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to upload image');
        }
        setReference(await response.json());
    } catch (error) {
        alert('Error: ' + error.message);
    } finally {
        drop?.removeAttribute('aria-busy');
    }
}

// Use the image in the viewer as the reference for an edit
async function useCurrentAsReference() {
    if (!currentImageId) return;

    try {
        const response = await fetch(`/api/references/from-image/${currentImageId}`, { method: 'POST' });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to use image as reference');
        }
        const ref = await response.json();

        // If we're not on the generate page, hand it over via sessionStorage
        if (!document.getElementById('generateForm')) {
            sessionStorage.setItem('reuseReference', JSON.stringify(ref));
            window.location.href = '/';
            return;
        }

        setReference(ref);
        const promptField = document.getElementById('prompt');
        if (promptField) {
            promptField.focus();
            promptField.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Only some models accept a reference image; the Qwen-only options hide for Ollama models
function updateModelOptions() {
    const modelField = document.getElementById('model');
    if (!modelField) return;

    const editing = referenceImage !== null;
    let selectedDisabled = false;
    for (const option of modelField.options) {
        if (option.value === '__all__') continue;
        option.disabled = editing && option.dataset.backend !== 'qwen';
        if (option.selected && option.disabled) selectedDisabled = true;
    }
    if (selectedDisabled) {
        const qwenOption = Array.from(modelField.options).find(o => o.dataset.backend === 'qwen');
        if (qwenOption) modelField.value = qwenOption.value;
    }

    const selected = modelField.options[modelField.selectedIndex];
    const usesQwen = modelField.value === '__all__' || selected?.dataset.backend === 'qwen';
    const qwenOptions = document.getElementById('qwenOptions');
    if (qwenOptions) qwenOptions.style.display = usesQwen ? 'flex' : 'none';

    const btn = document.getElementById('generateBtn');
    if (btn) btn.textContent = editing ? 'Edit Image' : 'Generate';

    const promptField = document.getElementById('prompt');
    if (promptField) {
        promptField.placeholder = editing
            ? 'Describe the edit: what to change, and what to keep...'
            : 'Describe the image you want to generate...';
    }
}

function initReferenceInput() {
    const drop = document.getElementById('referenceDrop');
    const fileInput = document.getElementById('referenceFile');
    const modelField = document.getElementById('model');
    if (!drop || !fileInput) return;

    drop.addEventListener('click', () => fileInput.click());
    drop.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileInput.click();
        }
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) uploadReference(fileInput.files[0]);
    });

    drop.addEventListener('dragover', (e) => {
        e.preventDefault();
        drop.classList.add('dragover');
    });
    drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
    drop.addEventListener('drop', (e) => {
        e.preventDefault();
        drop.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) uploadReference(file);
    });

    // Paste an image anywhere on the page to use it as the reference
    document.addEventListener('paste', (e) => {
        const item = Array.from(e.clipboardData?.items || []).find(i => i.type.startsWith('image/'));
        if (item) {
            e.preventDefault();
            uploadReference(item.getAsFile());
        }
    });

    document.getElementById('referencePreview')?.addEventListener('error', () => {
        if (referenceImage) clearReference();
    });

    modelField?.addEventListener('change', updateModelOptions);
    updateModelOptions();
}

// ============ Form persistence ============

// The Create form survives navigating to other pages (and reloads)
const FORM_STATE_KEY = 'createFormState';
const FORM_STATE_FIELDS = ['prompt', 'model', 'varyMode', 'width', 'height', 'steps', 'seed', 'count'];
let restoringFormState = false;

function saveFormState() {
    // While restoring, the form is half-filled; don't overwrite the saved state with it
    if (restoringFormState || !document.getElementById('generateForm')) return;
    const state = { reference: referenceImage };
    for (const id of FORM_STATE_FIELDS) {
        const field = document.getElementById(id);
        if (field) state[id] = field.value;
    }
    try {
        localStorage.setItem(FORM_STATE_KEY, JSON.stringify(state));
    } catch (e) {
        console.error('Failed to save form state:', e);
    }
}

function restoreFormState() {
    const form = document.getElementById('generateForm');
    if (!form) return;

    let state = null;
    try {
        state = JSON.parse(localStorage.getItem(FORM_STATE_KEY));
    } catch (e) {
        console.error('Failed to load form state:', e);
    }

    if (state) {
        restoringFormState = true;
        // The reference decides which models are selectable, so set it before the model
        if (state.reference) setReference(state.reference);
        for (const id of FORM_STATE_FIELDS) {
            const field = document.getElementById(id);
            if (field && state[id] !== undefined) field.value = state[id];
        }
        updateModelOptions();
        restoringFormState = false;
    }

    form.addEventListener('input', saveFormState);
    form.addEventListener('change', saveFormState);
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

// Refresh recent images display (gallery sidebar)
async function refreshRecentImages() {
    const galleryImages = document.getElementById('galleryImages');
    if (!galleryImages) return;

    // Remember current gallery index before refresh
    const currentIndex = currentGalleryIndex;

    try {
        const response = await fetch('/partials/recent-images');
        if (response.ok) {
            galleryImages.innerHTML = await response.text();

            const images = galleryImages.querySelectorAll('.image-card img');

            // Apply thumbnail size preference to newly loaded images
            images.forEach(img => {
                img.style.height = `${galleryPreferences.thumbnailSize}px`;
            });

            // Auto-display the first (most recent) image in viewer if viewer is empty
            const imageViewer = document.getElementById('imageViewer');
            if (imageViewer && imageViewer.querySelector('.image-viewer-placeholder')) {
                const firstImage = images[0];
                if (firstImage) {
                    displayImageInViewer(firstImage);
                }
            } else if (images.length > 0) {
                // Restore the previously selected image or select the first one
                const imageToDisplay = images[Math.min(currentIndex, images.length - 1)];
                if (imageToDisplay) {
                    displayImageInViewer(imageToDisplay);
                }
            }
        }
    } catch (error) {
        console.error('Failed to refresh images:', error);
    }
}

// Track current image index and list for navigation
let currentImageIndex = -1;
let currentImageList = [];

// Gallery preferences
let galleryPreferences = {
    thumbnailSize: 180,
    autoShowNew: true,
    galleryWidth: 300
};

// Display image in center viewer
function displayImageInViewer(imgElement) {
    const imageViewer = document.getElementById('imageViewer');
    const imageViewerInfo = document.getElementById('imageViewerInfo');

    if (!imageViewer) return;

    const imageSrc = imgElement.src;
    const prompt = imgElement.dataset.prompt || '';
    const originalPrompt = imgElement.dataset.originalPrompt || '';
    const model = imgElement.dataset.model || '';
    const width = imgElement.dataset.width || '';
    const height = imgElement.dataset.height || '';
    const reference = imgElement.dataset.reference || '';
    const seed = imgElement.dataset.seed || '';
    const steps = imgElement.dataset.steps || '';

    // Store current image metadata for reuse buttons
    currentImageMetadata = {
        prompt: prompt,
        originalPrompt: originalPrompt,
        model: model,
        width: width,
        height: height,
        reference: reference,
        seed: seed,
        steps: steps
    };

    // Update current gallery index to match this image
    const galleryImages = document.getElementById('galleryImages');
    if (galleryImages) {
        const images = galleryImages.querySelectorAll('.image-card img');
        currentGalleryIndex = Array.from(images).indexOf(imgElement);
        if (currentGalleryIndex === -1) currentGalleryIndex = 0;

        // Store current image ID for deletion
        const activeCard = imgElement.closest('.image-card');
        if (activeCard) {
            currentImageId = activeCard.id.replace('image-', '');
            activeCard.classList.add('active');
        }

        // Highlight the active image in gallery
        const cards = galleryImages.querySelectorAll('.image-card');
        cards.forEach(card => card.classList.remove('active'));
        if (activeCard) {
            activeCard.classList.add('active');
        }
    }

    // Update viewer content
    let infoHtml = '';
    if (originalPrompt && originalPrompt.trim()) {
        infoHtml = `
            <div class="prompt-section">
                <div class="prompt-label original">Original Prompt</div>
                <div class="prompt-text">${escapeHtml(originalPrompt)}</div>
            </div>
            <div class="prompt-section" style="margin-top: 0.75rem;">
                <div class="prompt-label">Varied Prompt (used for generation)</div>
                <div class="prompt-text">${escapeHtml(prompt)}</div>
            </div>
        `;
    } else if (prompt) {
        infoHtml = `
            <div class="prompt-section">
                <div class="prompt-label">Prompt</div>
                <div class="prompt-text">${escapeHtml(prompt)}</div>
            </div>
        `;
    }

    if (reference) {
        infoHtml = `
            <div class="prompt-section viewer-reference">
                <img src="/uploads/${escapeHtml(reference)}" alt="Reference image" title="Reference image (click to enlarge)"
                     onclick="openModal(this.src, '', null)">
                <div class="prompt-label">Edited from reference</div>
            </div>
        ` + infoHtml;
    }

    const details = [model, width && height ? `${width}×${height}` : '', steps ? `${steps} steps` : '', seed !== '' ? `seed ${seed}` : '']
        .filter(Boolean).join(' · ');
    if (details) {
        infoHtml += `<div class="image-details">${escapeHtml(details)}</div>`;
    }

    imageViewer.innerHTML = `<img src="${imageSrc}" alt="${escapeHtml(prompt)}" style="cursor: zoom-in;" onclick="openModal('${imageSrc}', \`${prompt}\`, \`${originalPrompt}\`)">`;
    imageViewerInfo.innerHTML = infoHtml;
    imageViewerInfo.style.display = infoHtml ? 'block' : 'none';
}

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

    // If this is from gallery sidebar, display in viewer instead of modal
    if (imgElement.closest('.gallery-sidebar')) {
        displayImageInViewer(imgElement);
        return;
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

// Track current gallery image index for keyboard navigation
let currentGalleryIndex = 0;
let currentImageId = null;
let currentImageMetadata = null;

// Navigate to previous gallery image
function navigatePrevGalleryImage() {
    const galleryImages = document.getElementById('galleryImages');
    if (!galleryImages) return;

    const images = galleryImages.querySelectorAll('.image-card img');
    if (images.length === 0) return;

    currentGalleryIndex = currentGalleryIndex > 0 ? currentGalleryIndex - 1 : images.length - 1;
    displayImageInViewer(images[currentGalleryIndex]);

    // Scroll the gallery to show the selected image
    images[currentGalleryIndex].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Navigate to next gallery image
function navigateNextGalleryImage() {
    const galleryImages = document.getElementById('galleryImages');
    if (!galleryImages) return;

    const images = galleryImages.querySelectorAll('.image-card img');
    if (images.length === 0) return;

    currentGalleryIndex = currentGalleryIndex < images.length - 1 ? currentGalleryIndex + 1 : 0;
    displayImageInViewer(images[currentGalleryIndex]);

    // Scroll the gallery to show the selected image
    images[currentGalleryIndex].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Handle keyboard navigation
document.addEventListener('keydown', function(event) {
    const modal = document.getElementById('imageModal');
    const isModalOpen = modal && modal.classList.contains('active');

    // Don't intercept if user is typing in an input/textarea
    const isTyping = event.target.tagName === 'INPUT' ||
                     event.target.tagName === 'TEXTAREA' ||
                     event.target.tagName === 'SELECT' ||
                     event.target.isContentEditable;

    // Modal navigation
    if (event.key === 'Escape') {
        closeModal();
        return;
    }

    if (isModalOpen) {
        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            navigatePrevImage();
        } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            navigateNextImage();
        }
        return;
    }

    // Don't handle other shortcuts if typing
    if (isTyping) return;

    // Page navigation
    if (event.key === '1') {
        event.preventDefault();
        window.location.href = '/';
    } else if (event.key === '2') {
        event.preventDefault();
        window.location.href = '/queue';
    }

    // Gallery navigation
    else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        navigatePrevGalleryImage();
    } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        navigateNextGalleryImage();
    }

    // Edit current image (use it as the reference)
    else if (event.key === 'e' || event.key === 'E') {
        event.preventDefault();
        useCurrentAsReference();
    }

    // Delete current image
    else if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        deleteCurrentImage();
    }
});

// Global SSE connection
let eventSource = null;

// Update queue summary in top bar
function updateQueueSummary(data) {
    const pendingCount = document.getElementById('pendingCount');
    const processingCount = document.getElementById('processingCount');

    if (pendingCount && processingCount) {
        const pending = data.jobs ? data.jobs.filter(j => j.status === 'pending').length : 0;
        const processing = data.jobs ? data.jobs.filter(j => j.status === 'processing').length : 0;

        pendingCount.textContent = pending;
        processingCount.textContent = processing;
    }
}

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
        updateQueueSummary(data);
        refreshQueue();
    });

    eventSource.addEventListener('job_added', function(e) {
        refreshQueue();
        refreshQueueSummary();
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
        refreshQueueSummary();

        // Refresh gallery and update viewer with new image if auto-show is enabled
        setTimeout(async function() {
            await refreshRecentImages();

            // Display the newly generated image in the viewer only if auto-show is enabled
            if (galleryPreferences.autoShowNew) {
                const galleryImages = document.getElementById('galleryImages');
                if (galleryImages) {
                    const firstImage = galleryImages.querySelector('.image-card img');
                    if (firstImage) {
                        displayImageInViewer(firstImage);
                    }
                }
            }
        }, 100);
    });

    eventSource.addEventListener('job_failed', function(e) {
        refreshQueue();
        refreshQueueSummary();
    });

    eventSource.addEventListener('job_cancelled', function(e) {
        refreshQueue();
        refreshQueueSummary();
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

// Refresh queue summary from API
async function refreshQueueSummary() {
    try {
        const response = await fetch('/api/queue');
        if (response.ok) {
            const data = await response.json();
            updateQueueSummary(data);
        }
    } catch (error) {
        console.error('Failed to refresh queue summary:', error);
    }
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

// Load gallery preferences from localStorage
function loadGalleryPreferences() {
    const saved = localStorage.getItem('galleryPreferences');
    if (saved) {
        try {
            galleryPreferences = { ...galleryPreferences, ...JSON.parse(saved) };
        } catch (e) {
            console.error('Failed to load gallery preferences:', e);
        }
    }
}

// Save gallery preferences to localStorage
function saveGalleryPreferences() {
    try {
        localStorage.setItem('galleryPreferences', JSON.stringify(galleryPreferences));
    } catch (e) {
        console.error('Failed to save gallery preferences:', e);
    }
}

// Update thumbnail size
function updateThumbnailSize(size) {
    galleryPreferences.thumbnailSize = size;
    saveGalleryPreferences();

    // Update CSS custom property for grid min size (slightly larger than thumbnail for padding/borders)
    const gridMin = Math.max(60, size + 20);
    document.documentElement.style.setProperty('--thumbnail-grid-min', `${gridMin}px`);

    // Update thumbnail heights
    const galleryImages = document.getElementById('galleryImages');
    if (galleryImages) {
        const images = galleryImages.querySelectorAll('.image-card img');
        images.forEach(img => {
            img.style.height = `${size}px`;
        });
    }

    // Update label
    const sizeValue = document.getElementById('thumbnailSizeValue');
    if (sizeValue) {
        sizeValue.textContent = `${size}px`;
    }
}

// Update gallery width
function updateGalleryWidth(width) {
    galleryPreferences.galleryWidth = width;
    saveGalleryPreferences();

    // Update CSS custom property
    document.documentElement.style.setProperty('--gallery-width', `${width}px`);
}

// Initialize gallery resize handle
function initGalleryResize() {
    const handle = document.getElementById('galleryResizeHandle');
    if (!handle) return;

    let isDragging = false;
    let startX = 0;
    let startWidth = 0;

    handle.addEventListener('mousedown', function(e) {
        isDragging = true;
        startX = e.clientX;
        startWidth = galleryPreferences.galleryWidth;
        handle.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;

        const delta = startX - e.clientX;
        const newWidth = Math.max(250, Math.min(800, startWidth + delta));
        updateGalleryWidth(newWidth);
    });

    document.addEventListener('mouseup', function() {
        if (isDragging) {
            isDragging = false;
            handle.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

// Initialize gallery controls
function initGalleryControls() {
    const thumbnailSize = document.getElementById('thumbnailSize');
    const autoShowNew = document.getElementById('autoShowNew');

    // Initialize gallery width
    updateGalleryWidth(galleryPreferences.galleryWidth);

    if (thumbnailSize) {
        thumbnailSize.value = galleryPreferences.thumbnailSize;
        updateThumbnailSize(galleryPreferences.thumbnailSize);

        thumbnailSize.addEventListener('input', function(e) {
            updateThumbnailSize(parseInt(e.target.value, 10));
        });
    }

    if (autoShowNew) {
        autoShowNew.checked = galleryPreferences.autoShowNew;

        autoShowNew.addEventListener('change', function(e) {
            galleryPreferences.autoShowNew = e.target.checked;
            saveGalleryPreferences();
        });
    }

    // Initialize resize handle
    initGalleryResize();
}

// Initialize SSE on all pages for queue summary updates
setupSSE();

// Initialize queue summary on page load
refreshQueueSummary();

// Load preferences
loadGalleryPreferences();

// Initialize image viewer with most recent image on page load
document.addEventListener('DOMContentLoaded', function() {
    // Initialize gallery controls
    initGalleryControls();

    const galleryImages = document.getElementById('galleryImages');
    const imageViewer = document.getElementById('imageViewer');

    if (galleryImages && imageViewer) {
        const firstImage = galleryImages.querySelector('.image-card img');
        if (firstImage) {
            displayImageInViewer(firstImage);
        }
    }

    initReferenceInput();
    restoreFormState();

    // Restore reused parameters (these override the saved form) from sessionStorage if present
    const reuseAllData = sessionStorage.getItem('reuseAll');
    const reusePromptData = sessionStorage.getItem('reusePrompt');
    const reuseReferenceData = sessionStorage.getItem('reuseReference');

    if (reuseAllData) {
        try {
            applyFormParams(JSON.parse(reuseAllData));
        } catch (e) {
            console.error('Failed to restore reuse data:', e);
        }
        // Clear the stored data
        sessionStorage.removeItem('reuseAll');
    } else if (reusePromptData) {
        const promptField = document.getElementById('prompt');
        if (promptField) {
            promptField.value = reusePromptData;
            saveFormState();
            promptField.focus();
            promptField.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        // Clear the stored data
        sessionStorage.removeItem('reusePrompt');
    } else if (reuseReferenceData) {
        try {
            setReference(JSON.parse(reuseReferenceData));
            document.getElementById('prompt')?.focus();
        } catch (e) {
            console.error('Failed to restore reference:', e);
        }
        sessionStorage.removeItem('reuseReference');
    }
});
