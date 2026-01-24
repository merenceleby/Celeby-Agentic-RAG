import React, { useState } from 'react'
import ChatInterface from './components/ChatInterface'
import DocumentsList from './components/DocumentsList'
import './App.css'

function App() {
  const [documentUpdate, setDocumentUpdate] = useState(0)

  const handleDocumentChange = () => {
    setDocumentUpdate(prev => prev + 1)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 Self-Correcting RAG Agent</h1>
        <p className="subtitle">Advanced RAG with Query Rewriting, Hybrid Search & Re-ranking</p>
{/*         <div className="tech-stack">
          <span className="tech-badge">Phi-3 Mini</span>
          <span className="tech-badge">LangGraph</span>
          <span className="tech-badge">ChromaDB</span>
          <span className="tech-badge">Cross-Encoder</span>
          <span className="tech-badge">BM25</span>
        </div> */}
      </header>
      
      <div className="app-container">
        <DocumentsList onDocumentChange={handleDocumentChange} key={documentUpdate} />
        <ChatInterface onDocumentChange={handleDocumentChange} />
      </div>
    </div>
  )
}

export default App