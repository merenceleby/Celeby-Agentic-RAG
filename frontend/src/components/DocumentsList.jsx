import React, { useState, useEffect } from 'react'
import axios from 'axios'
import './DocumentsList.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function DocumentsList({ onDocumentChange, refreshTrigger }) {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(false)

  const fetchDocuments = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/documents`)
      setDocuments(response.data.documents || [])
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    }
  }

  useEffect(() => {
    fetchDocuments()
  }, [refreshTrigger])

  const handleDelete = async (filename) => {
    if (!confirm(`Delete "${filename}"?\n\nThis will remove it from the database and all related chunks.`)) return

    try {
      setLoading(true)
      await axios.delete(`${API_URL}/api/documents/${encodeURIComponent(filename)}`)
      await fetchDocuments()
      if (onDocumentChange) onDocumentChange()
      alert(`✅ Document "${filename}" deleted successfully!`)
    } catch (error) {
      alert('❌ Delete failed: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="documents-list">
      <div className="documents-header">
        <h2>📄 Uploaded Documents</h2>
        <button 
          className="refresh-btn" 
          onClick={fetchDocuments}
          disabled={loading}
          title="Refresh list"
        >
          🔄
        </button>
      </div>
      
      {documents.length === 0 ? (
        <div className="empty-state">
          <p>No documents uploaded yet.</p>
          <p className="hint">Upload a PDF to get started!</p>
        </div>
      ) : (
        <div className="documents-grid">
          {documents.map((doc, idx) => (
            <div key={idx} className="document-item">
              <div className="document-info">
                <div className="document-icon">📄</div>
                <div className="document-details">
                  <div className="document-name" title={doc.name}>
                    {doc.name.length > 25 ? doc.name.substring(0, 25) + '...' : doc.name}
                  </div>
                  <div className="document-meta">
                    {doc.chunks || 0} chunks
                  </div>
                </div>
              </div>
              <button 
                className="delete-btn" 
                onClick={() => handleDelete(doc.name)}
                disabled={loading}
                title="Delete document"
              >
                ❌
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default DocumentsList