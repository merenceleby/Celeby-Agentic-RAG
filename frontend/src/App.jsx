import React, { useState, useEffect } from 'react'
import ChatInterface from './components/ChatInterface'
import MetricsDashboard from './components/MetricsDashboard'
import './App.css'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function App() {
  const [metrics, setMetrics] = useState({
    total_queries: 0,
    total_corrections: 0,
    correction_rate: 0,
    avg_latency_ms: 0,
    p95_latency_ms: 0,
    cache_hit_rate: 0
  })

  const [localMetrics, setLocalMetrics] = useState({
    totalQueries: 0,
    corrections: 0,
    avgResponseTime: 0
  })

  // Fetch metrics from backend
  const fetchMetrics = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/metrics`)
      setMetrics(response.data)
    } catch (error) {
      console.error('Failed to fetch metrics:', error)
    }
  }

  // Fetch metrics on mount and every 10 seconds
  useEffect(() => {
    fetchMetrics()
    const interval = setInterval(fetchMetrics, 10000)
    return () => clearInterval(interval)
  }, [])

  const updateLocalMetrics = (wasCorrect, responseTime) => {
    setLocalMetrics(prev => ({
      totalQueries: prev.totalQueries + 1,
      corrections: prev.corrections + (wasCorrect ? 1 : 0),
      avgResponseTime: ((prev.avgResponseTime * prev.totalQueries) + responseTime) / (prev.totalQueries + 1)
    }))
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 Self-Correcting RAG Agent</h1>
        {/* <p className="subtitle">Advanced RAG with Query Rewriting, Hybrid Search & Re-ranking</p>
        <div className="tech-stack">
          <span className="tech-badge">Phi-3 Mini</span>
          <span className="tech-badge">LangGraph</span>
          <span className="tech-badge">ChromaDB</span>
          <span className="tech-badge">Cross-Encoder</span>
          <span className="tech-badge">BM25</span>
        </div> */}
      </header>
      
      <div className="app-container">
        <MetricsDashboard metrics={metrics} localMetrics={localMetrics} />
        <ChatInterface onMetricsUpdate={updateLocalMetrics} onQueryComplete={fetchMetrics} />
      </div>
    </div>
  )
}

export default App