// Resume Evaluator specific JavaScript
document.addEventListener('DOMContentLoaded', function() {
    const evaluationForm = document.getElementById('evaluationForm');
    const feedbackForm = document.getElementById('feedbackForm');
    const resultDiv = document.getElementById('evaluation-result');
    const submitBtn = document.getElementById('submitBtn');

    if (evaluationForm) {
        evaluationForm.addEventListener('submit', handleEvaluationSubmit);
    }

    if (feedbackForm) {
        feedbackForm.addEventListener('submit', handleFeedbackSubmit);
    }
});

async function handleEvaluationSubmit(e) {
    e.preventDefault();
    if (!utils.validateForm('evaluationForm')) {
        return;
    }

    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Evaluating...';

    try {
        const formData = new FormData(e.target);
        const response = await fetch('/evaluate', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }

        displayResults(data);
    } catch (error) {
        utils.handleError(error);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Evaluate Resume';
    }
}

function displayResults(data) {
    const resultDiv = document.getElementById('evaluation-result');
    resultDiv.style.display = 'block';

    // Update match score
    const progressBar = document.getElementById('progress-bar');
    utils.animateProgressBar(progressBar, data.match_percentage);

    // Update match factors
    updateMatchFactors(data.match_factors);

    // Update job stability
    updateJobStability(data.job_stability);

    // Update profile information
    updateProfileInfo(data);

    // Update interview questions
    updateInterviewQuestions(data);

    // Set evaluation ID for feedback
    document.getElementById('evaluation-id').value = data.id;
}

function updateMatchFactors(factors) {
    Object.entries(factors).forEach(([factor, value]) => {
        const element = document.getElementById(factor.toLowerCase().replace(' ', '-'));
        if (element) {
            element.style.width = `${value}%`;
            element.nextElementSibling.textContent = `${value}%`;
        }
    });
}

function updateJobStability(stability) {
    const stabilityBar = document.getElementById('stability-score-bar');
    utils.animateProgressBar(stabilityBar, stability.StabilityScore);

    document.getElementById('risk-level').textContent = stability.RiskLevel;
    document.getElementById('risk-level').className = `badge bg-${getRiskLevelColor(stability.RiskLevel)}`;
    document.getElementById('average-tenure').textContent = stability.AverageJobTenure;
    document.getElementById('job-count').textContent = stability.JobCount;
    document.getElementById('stability-explanation').textContent = stability.ReasoningExplanation;
}

function getRiskLevelColor(riskLevel) {
    switch (riskLevel.toLowerCase()) {
        case 'low': return 'success';
        case 'medium': return 'warning';
        case 'high': return 'danger';
        default: return 'secondary';
    }
}

function updateProfileInfo(data) {
    document.getElementById('profile-summary').textContent = data.profile_summary;
    
    const missingKeywords = document.getElementById('missing-keywords');
    missingKeywords.innerHTML = data.missing_keywords.length > 0 
        ? `<ul>${data.missing_keywords.map(kw => `<li>${kw}</li>`).join('')}</ul>` 
        : 'No missing keywords identified.';
    
    document.getElementById('extra-info').textContent = data.extra_info || 'No additional information provided.';
}

function updateInterviewQuestions(data) {
    const questions = {
        'quick-checks-questions': data.behavioral_questions,
        'soft-skills-questions': data.nontechnical_questions,
        'technical-skills-questions': data.technical_questions
    };

    Object.entries(questions).forEach(([listId, questionList]) => {
        const list = document.getElementById(listId);
        if (list) {
            list.innerHTML = questionList.map(q => `<li class="list-group-item">${q}</li>`).join('');
        }
    });
}

async function handleFeedbackSubmit(e) {
    e.preventDefault();
    if (!utils.validateForm('feedbackForm')) {
        return;
    }

    try {
        const formData = new FormData(e.target);
        const feedbackData = {
            evaluation_id: formData.get('evaluation_id'),
            rating: formData.get('rating'),
            comments: formData.get('comments')
        };

        await utils.submitFeedback(
            feedbackData.evaluation_id,
            feedbackData.rating,
            feedbackData.comments
        );

        alert('Feedback submitted successfully!');
        e.target.reset();
    } catch (error) {
        utils.handleError(error);
    }
} 