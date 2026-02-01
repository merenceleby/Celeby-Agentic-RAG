import React, { useState } from 'react'
import ChatInterface from './components/ChatInterface'
import DocumentsList from './components/DocumentsList'
import ChatSidebar from './components/ChatSidebar'
import './App.css'

function App() {
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  
  // CRITICAL: Start with null so no conversation is created automatically
  const [conversationId, setConversationId] = useState(null)
  
  const [conversationListRefresh, setConversationListRefresh] = useState(0)

  const handleDocumentChange = () => {
    setRefreshTrigger(prev => prev + 1)
  }

  const handleConversationActivity = () => {
    setConversationListRefresh(prev => prev + 1)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 Celeby Agentic RAG 🤖</h1>
        {/* <h1>🤖 Celeby Agentic RAG 🤖</h1> */}
        <p className="subtitle">
          <span>Celeby did</span>
          <span>Celeby money</span>
          <span>Celeby blood</span>
        </p>
        <p className="normal-description">Advanced RAG with Query Rewriting, Hybrid Search & Re-ranking</p>
        {/* <div className="tech-stack">
          <span className="tech-badge">Phi-3 Mini</span>
          <span className="tech-badge">LangGraph</span>
          <span className="tech-badge">ChromaDB</span>
          <span className="tech-badge">Cross-Encoder</span>
          <span className="tech-badge">BM25</span>
        </div> */}
      </header>
      
      <div className="app-container">
        <ChatSidebar
          currentConversationId={conversationId}
          onSelectConversation={setConversationId}
          refreshTrigger={conversationListRefresh}
        />
        <ChatInterface
          conversationId={conversationId}
          onConversationCreated={(id) => {
            setConversationId(id)
            handleConversationActivity()
          }}
          onConversationActivity={handleConversationActivity}
          onDocumentChange={handleDocumentChange}
        />
        <DocumentsList 
          onDocumentChange={handleDocumentChange} 
          refreshTrigger={refreshTrigger}
        />
      </div>
    </div>
  )
}

export default App