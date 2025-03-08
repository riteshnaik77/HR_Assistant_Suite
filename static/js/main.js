// Dark Mode Toggle
function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    const isDarkMode = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDarkMode);
}

// Initialize dark mode from localStorage
document.addEventListener('DOMContentLoaded', function() {
    const isDarkMode = localStorage.getItem('darkMode') === 'true';
    if (isDarkMode) {
        document.body.classList.add('dark-mode');
    }
});

// Form Validation
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return true;

    let isValid = true;
    const requiredFields = form.querySelectorAll('[required]');

    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            isValid = false;
            field.classList.add('is-invalid');
        } else {
            field.classList.remove('is-invalid');
        }
    });

    return isValid;
}

// File Upload Preview
function handleFileUpload(input) {
    if (input.files && input.files[0]) {
        const file = input.files[0];
        const fileType = file.type;
        const maxSize = 5 * 1024 * 1024; // 5MB

        if (file.size > maxSize) {
            alert('File size must be less than 5MB');
            input.value = '';
            return;
        }

        if (!['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'].includes(fileType)) {
            alert('Please upload a PDF or DOCX file');
            input.value = '';
            return;
        }
    }
}

// Progress Bar Animation
function animateProgressBar(element, targetValue, duration = 1000) {
    const startValue = 0;
    const startTime = performance.now();

    function updateProgress(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);

        const currentValue = startValue + (targetValue - startValue) * progress;
        element.style.width = `${currentValue}%`;
        element.textContent = `${Math.round(currentValue)}%`;

        if (progress < 1) {
            requestAnimationFrame(updateProgress);
        }
    }

    requestAnimationFrame(updateProgress);
}

// Feedback Submission
function submitFeedback(evaluationId, rating, comments) {
    return fetch('/feedback', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            evaluation_id: evaluationId,
            rating: rating,
            comments: comments
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            throw new Error(data.error);
        }
        return data;
    });
}

// Error Handling
function handleError(error) {
    console.error('Error:', error);
    alert(error.message || 'An error occurred. Please try again.');
}

// Export functions for use in other files
window.utils = {
    toggleDarkMode,
    validateForm,
    handleFileUpload,
    animateProgressBar,
    submitFeedback,
    handleError
}; 