import React, { useState, useEffect } from 'react'
import axios from 'axios'
import './AdminPanel.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function AdminPanel() {
  const [metrics, setMetrics] = useState(null)
  const [evaluationResult, setEvaluationResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [datasetSize, setDatasetSize] = useState(20)

  useEffect(() => {
    fetchMetrics()
    const interval = setInterval(fetchMetrics, 10000)
    return () => clearInterval(interval)
  }, [])

  const fetchMetrics = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/metrics`)
      setMetrics(response.data)
    } catch (error) {
      console.error('Failed to fetch metrics:', error)
    }
  }

  const handleGenerateDataset = async () => {
    if (!confirm(`Generate ${datasetSize} test cases?`)) return

    try {
      setLoading(true)
      const response = await axios.post(
        `${API_URL}/api/evaluation/generate-dataset?n_questions=${datasetSize}`
      )
      alert(`✅ Generated ${response.data.dataset.length} test cases!`)
      console.log('Dataset:', response.data.dataset)
    } catch (error) {
      alert('❌ Dataset generation failed: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  const handleRunEvaluation = async () => {
    if (!confirm('Run RAGAS evaluation? This may take several minutes.')) return

    try {
      setLoading(true)
      const response = await axios.post(`${API_URL}/api/evaluation/run`)
      setEvaluationResult(response.data)
      
      alert(`✅ Evaluation Complete!\n\n` +
            `Faithfulness: ${(response.data.avg_faithfulness * 100).toFixed(1)}%\n` +
            `Relevancy: ${(response.data.avg_relevancy * 100).toFixed(1)}%\n` +
            `Recall: ${(response.data.avg_recall * 100).toFixed(1)}%`)
    } catch (error) {
      alert('❌ Evaluation failed: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  const handleResetMetrics = async () => {
    if (!confirm('Reset all metrics?')) return

    try {
      await axios.post(`${API_URL}/api/metrics/reset`)
      fetchMetrics()
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
        {/* System Metrics */}
        <section className="admin-section">
          <h2>📊 System Metrics</h2>
          {metrics ? (
            <div className="metrics-grid">
              <div className="metric-card">
                <div className="metric-label">Total Queries</div>
                <div className="metric-value">{metrics.total_queries || 0}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Self-Corrections</div>
                <div className="metric-value">{metrics.total_corrections || 0}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Correction Rate</div>
                <div className="metric-value">
                  {((metrics.correction_rate || 0) * 100).toFixed(1)}%
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Avg Latency</div>
                <div className="metric-value">
                  {(metrics.avg_latency_ms || 0).toFixed(0)}ms
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">P95 Latency</div>
                <div className="metric-value">
                  {(metrics.p95_latency_ms || 0).toFixed(0)}ms
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">P99 Latency</div>
                <div className="metric-value">
                  {(metrics.p99_latency_ms || 0).toFixed(0)}ms
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Cache Hit Rate</div>
                <div className="metric-value">
                  {((metrics.cache_hit_rate || 0) * 100).toFixed(1)}%
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Error Rate</div>
                <div className="metric-value">
                  {((metrics.error_rate || 0) * 100).toFixed(1)}%
                </div>
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

        {/* Evaluation Tools */}
        <section className="admin-section">
          <h2>🧪 Evaluation Tools</h2>
          
          <div className="evaluation-controls">
            <div className="control-item">
              <label>
                Dataset Size:
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
                className="admin-btn primary"
                onClick={handleRunEvaluation}
                disabled={loading}
              >
                ✅ Run RAGAS Evaluation
              </button>
            </div>
          </div>

          {loading && (
            <div className="loading-indicator">
              <div className="spinner"></div>
              <p>Processing... This may take a few minutes.</p>
            </div>
          )}

          {evaluationResult && (
            <div className="evaluation-results">
              <h3>Latest Evaluation Results</h3>
              <div className="results-grid">
                <div className="result-card">
                  <div className="result-label">Faithfulness</div>
                  <div className="result-value">
                    {(evaluationResult.avg_faithfulness * 100).toFixed(1)}%
                  </div>
                  <div className="result-desc">Answer accuracy vs context</div>
                </div>
                <div className="result-card">
                  <div className="result-label">Relevancy</div>
                  <div className="result-value">
                    {(evaluationResult.avg_relevancy * 100).toFixed(1)}%
                  </div>
                  <div className="result-desc">Answer relevance to question</div>
                </div>
                <div className="result-card">
                  <div className="result-label">Recall</div>
                  <div className="result-value">
                    {(evaluationResult.avg_recall * 100).toFixed(1)}%
                  </div>
                  <div className="result-desc">Context retrieval quality</div>
                </div>
                <div className="result-card">
                  <div className="result-label">Test Cases</div>
                  <div className="result-value">
                    {evaluationResult.num_cases}
                  </div>
                  <div className="result-desc">Total evaluated</div>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

export default AdminPanel