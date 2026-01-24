import React, { useState, useEffect } from 'react'
import axios from 'axios'
import './AdminPanel.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function AdminPanel() {
  const [metrics, setMetrics] = useState(null)
  const [feedbackStats, setFeedbackStats] = useState(null)
  const [evaluationResult, setEvaluationResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [datasetSize, setDatasetSize] = useState(20)

  useEffect(() => {
    fetchAllData()
    const interval = setInterval(fetchAllData, 10000)
    return () => clearInterval(interval)
  }, [])

  const fetchAllData = async () => {
    fetchMetrics()
    fetchFeedbackStats()
  }

  const fetchMetrics = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/metrics`)
      setMetrics(response.data)
    } catch (error) {
      console.error('Failed to fetch metrics:', error)
    }
  }

  const fetchFeedbackStats = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/feedback/stats`)
      setFeedbackStats(response.data)
    } catch (error) {
      console.error('Failed to fetch feedback stats:', error)
    }
  }

  const handleGenerateDataset = async () => {
    if (!confirm(`Generate ${datasetSize} test cases from your documents?\n\n` +
                 `This will create question-answer pairs for testing.`)) return

    try {
      setLoading(true)
      const response = await axios.post(
        `${API_URL}/api/evaluation/generate-dataset?n_questions=${datasetSize}`
      )
      
      const dataset = response.data.dataset
      
      alert(`✅ Generated ${dataset.length} test cases!\n\n` +
            `These are question-answer pairs created from your documents.\n` +
            `You can now run evaluation to test system quality.`)
      
      console.log('Generated Dataset:', dataset)
    } catch (error) {
      alert('❌ Dataset generation failed: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  const handleRunEvaluation = async () => {
    if (!confirm(
      '🧪 Run RAGAS Evaluation?\n\n' +
      'This will:\n' +
      '1. Generate test questions from your documents\n' +
      '2. Run the RAG system on each question\n' +
      '3. Measure answer quality with 3 metrics:\n' +
      '   • Faithfulness (accuracy)\n' +
      '   • Relevancy (relevance to question)\n' +
      '   • Recall (retrieval quality)\n\n' +
      'This may take 5-10 minutes.'
    )) return

    try {
      setLoading(true)
      const response = await axios.post(`${API_URL}/api/evaluation/run`)
      setEvaluationResult(response.data)
      
      const r = response.data
      alert(
        `✅ Evaluation Complete!\n\n` +
        `📊 Results (0-100%, higher is better):\n` +
        `• Faithfulness: ${(r.avg_faithfulness * 100).toFixed(1)}%\n` +
        `  (How accurate are answers based on sources)\n\n` +
        `• Relevancy: ${(r.avg_relevancy * 100).toFixed(1)}%\n` +
        `  (How relevant are answers to questions)\n\n` +
        `• Recall: ${(r.avg_recall * 100).toFixed(1)}%\n` +
        `  (How well did we find the right sources)\n\n` +
        `Tested on ${r.num_cases} question-answer pairs.`
      )
    } catch (error) {
      alert('❌ Evaluation failed: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  const handleResetMetrics = async () => {
    if (!confirm('Reset all performance metrics?')) return

    try {
      await axios.post(`${API_URL}/api/metrics/reset`)
      fetchAllData()
      alert('✅ Metrics reset successfully!')
    } catch (error) {
      alert('❌ Reset failed: ' + error.message)
    }
  }

  return (
    <div className="admin-panel">
      <header className="admin-header">
        <h1>⚙️ Admin Panel</h1>
        <a href="/" className="back-link">← Back to Chat</a>
      </header>

      <div className="admin-content">
        {/* System Performance Metrics */}
        <section className="admin-section">
          <div className="section-header">
            <h2>📊 System Performance Metrics</h2>
            <p className="section-desc">
              Real-time statistics about your RAG system's performance and usage
            </p>
          </div>
          
          {metrics ? (
            <div className="metrics-grid">
              <div className="metric-card">
                <div className="metric-label">Total Queries</div>
                <div className="metric-value">{metrics.total_queries || 0}</div>
                <div className="metric-desc">Questions asked</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Self-Corrections</div>
                <div className="metric-value">{metrics.total_corrections || 0}</div>
                <div className="metric-desc">Times system improved its answer</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Correction Rate</div>
                <div className="metric-value">
                  {((metrics.correction_rate || 0) * 100).toFixed(1)}%
                </div>
                <div className="metric-desc">% of queries corrected</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Avg Latency</div>
                <div className="metric-value">
                  {(metrics.avg_latency_ms || 0).toFixed(0)}ms
                </div>
                <div className="metric-desc">Average response time</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">P95 Latency</div>
                <div className="metric-value">
                  {(metrics.p95_latency_ms || 0).toFixed(0)}ms
                </div>
                <div className="metric-desc">95% of responses under</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">P99 Latency</div>
                <div className="metric-value">
                  {(metrics.p99_latency_ms || 0).toFixed(0)}ms
                </div>
                <div className="metric-desc">99% of responses under</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Cache Hit Rate</div>
                <div className="metric-value">
                  {((metrics.cache_hit_rate || 0) * 100).toFixed(1)}%
                </div>
                <div className="metric-desc">Queries served from cache</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Error Rate</div>
                <div className="metric-value">
                  {((metrics.error_rate || 0) * 100).toFixed(1)}%
                </div>
                <div className="metric-desc">Failed queries</div>
              </div>
            </div>
          ) : (
            <p>Loading metrics...</p>
          )}
          
          <button 
            className="admin-btn secondary" 
            onClick={handleResetMetrics}
          >
            🔄 Reset Metrics
          </button>
        </section>

        {/* User Feedback Stats */}
        {feedbackStats && feedbackStats.total_feedback > 0 && (
          <section className="admin-section">
            <div className="section-header">
              <h2>👥 User Feedback</h2>
              <p className="section-desc">
                Like/Dislike feedback from users on answer quality
              </p>
            </div>
            
            <div className="metrics-grid small">
              <div className="metric-card success-card">
                <div className="metric-label">👍 Likes</div>
                <div className="metric-value">{feedbackStats.likes || 0}</div>
              </div>
              <div className="metric-card danger-card">
                <div className="metric-label">👎 Dislikes</div>
                <div className="metric-value">{feedbackStats.dislikes || 0}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Satisfaction Rate</div>
                <div className="metric-value">
                  {feedbackStats.satisfaction_rate.toFixed(1)}%
                </div>
                <div className="metric-desc">Users who liked answers</div>
              </div>
            </div>
          </section>
        )}

        {/* RAGAS Evaluation Tools */}
        <section className="admin-section">
          <div className="section-header">
            <h2>🧪 RAGAS Evaluation</h2>
            <p className="section-desc">
              Automated quality testing for your RAG system using RAGAS framework
            </p>
          </div>
          
          <div className="info-box">
            <strong>What is RAGAS?</strong>
            <p>
              RAGAS (Retrieval Augmented Generation Assessment) automatically tests your RAG system by:
            </p>
            <ol>
              <li><strong>Generating test questions</strong> from your documents</li>
              <li><strong>Running your RAG system</strong> on each question</li>
              <li><strong>Measuring quality</strong> with 3 metrics:
                <ul>
                  <li><strong>Faithfulness:</strong> Are answers factually accurate?</li>
                  <li><strong>Relevancy:</strong> Do answers address the question?</li>
                  <li><strong>Recall:</strong> Did we retrieve the right documents?</li>
                </ul>
              </li>
            </ol>
          </div>

          <div className="evaluation-controls">
            <div className="control-item">
              <label>
                Test Cases to Generate:
                <input 
                  type="number" 
                  value={datasetSize}
                  onChange={(e) => setDatasetSize(parseInt(e.target.value))}
                  min="5"
                  max="100"
                  disabled={loading}
                />
              </label>
              <button 
                className="admin-btn primary"
                onClick={handleGenerateDataset}
                disabled={loading}
              >
                📊 Generate Test Dataset
              </button>
            </div>

            <div className="control-item">
              <button 
                className="admin-btn primary large"
                onClick={handleRunEvaluation}
                disabled={loading}
              >
                ✅ Run Full RAGAS Evaluation (5-10 min)
              </button>
            </div>
          </div>

          {loading && (
            <div className="loading-indicator">
              <div className="spinner"></div>
              <p>Processing evaluation... This may take several minutes.</p>
            </div>
          )}

          {evaluationResult && (
            <div className="evaluation-results">
              <h3>📈 Latest Evaluation Results</h3>
              <div className="results-grid">
                <div className="result-card">
                  <div className="result-label">Faithfulness</div>
                  <div className="result-value">
                    {(evaluationResult.avg_faithfulness * 100).toFixed(1)}%
                  </div>
                  <div className="result-desc">
                    Answers are factually accurate based on retrieved sources
                  </div>
                </div>
                <div className="result-card">
                  <div className="result-label">Relevancy</div>
                  <div className="result-value">
                    {(evaluationResult.avg_relevancy * 100).toFixed(1)}%
                  </div>
                  <div className="result-desc">
                    Answers directly address the questions asked
                  </div>
                </div>
                <div className="result-card">
                  <div className="result-label">Recall</div>
                  <div className="result-value">
                    {(evaluationResult.avg_recall * 100).toFixed(1)}%
                  </div>
                  <div className="result-desc">
                    System retrieved the right documents to answer
                  </div>
                </div>
                <div className="result-card">
                  <div className="result-label">Test Cases</div>
                  <div className="result-value">
                    {evaluationResult.num_cases}
                  </div>
                  <div className="result-desc">
                    Questions tested
                  </div>
                </div>
              </div>
              
              <div className="evaluation-summary">
                <strong>💡 What do these scores mean?</strong>
                <p>
                  Higher is better (0-100%). Aim for 80%+ on all metrics for production quality.
                  If scores are low, consider adjusting retrieval parameters or adding more documents.
                </p>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

export default AdminPanel