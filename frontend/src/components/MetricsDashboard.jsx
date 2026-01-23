import React from 'react'
import './MetricsDashboard.css'

function MetricsDashboard({ metrics, localMetrics }) {
  const correctionRate = metrics.total_queries > 0
    ? (metrics.correction_rate * 100).toFixed(1)
    : 0

  const cacheHitRate = metrics.cache_hit_rate
    ? (metrics.cache_hit_rate * 100).toFixed(1)
    : 0

  return (
    <div className="metrics-dashboard">
      <h2>📊 System Metrics</h2>
      
      <div className="metrics-section">
        <h3>Performance</h3>
        <div className="metrics-grid">
          <div className="metric-card primary">
            <div className="metric-icon">📈</div>
            <div className="metric-value">{metrics.total_queries || 0}</div>
            <div className="metric-label">Total Queries</div>
          </div>
          
          <div className="metric-card success">
            <div className="metric-icon">⚡</div>
            <div className="metric-value">
              {metrics.avg_latency_ms ? metrics.avg_latency_ms.toFixed(0) : 0}ms
            </div>
            <div className="metric-label">Avg Latency</div>
          </div>
          
          <div className="metric-card info">
            <div className="metric-icon">🎯</div>
            <div className="metric-value">
              {metrics.p95_latency_ms ? metrics.p95_latency_ms.toFixed(0) : 0}ms
            </div>
            <div className="metric-label">P95 Latency</div>
          </div>
        </div>
      </div>

      <div className="metrics-section">
        <h3>Self-Correction</h3>
        <div className="metrics-grid">
          <div className="metric-card warning">
            <div className="metric-icon">🔄</div>
            <div className="metric-value">{metrics.total_corrections || 0}</div>
            <div className="metric-label">Total Corrections</div>
          </div>
          
          <div className="metric-card accent">
            <div className="metric-icon">📊</div>
            <div className="metric-value">{correctionRate}%</div>
            <div className="metric-label">Correction Rate</div>
          </div>
        </div>
      </div>

      <div className="metrics-section">
        <h3>Optimization</h3>
        <div className="metrics-grid">
          <div className="metric-card success">
            <div className="metric-icon">💾</div>
            <div className="metric-value">{cacheHitRate}%</div>
            <div className="metric-label">Cache Hit Rate</div>
          </div>
          
          <div className="metric-card info">
            <div className="metric-icon">⏱️</div>
            <div className="metric-value">
              {metrics.uptime_seconds ? Math.floor(metrics.uptime_seconds / 60) : 0}m
            </div>
            <div className="metric-label">Uptime</div>
          </div>
        </div>
      </div>

      <div className="metrics-footer">
        <div className="status-indicator">
          <div className="status-dot active"></div>
          <span>System Active</span>
        </div>
      </div>
    </div>
  )
}

export default MetricsDashboard