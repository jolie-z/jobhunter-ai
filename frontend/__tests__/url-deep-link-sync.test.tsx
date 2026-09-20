import { describe, it, expect, beforeEach, vi } from "vitest"
import React, { useState, useEffect } from "react"
import { render, fireEvent } from "@testing-library/react"
import { setDeepLinkParam, clearDeepLinkParams } from "@/lib/deep-link"

describe("URL Deep Link & State Sync Guard", () => {
  beforeEach(() => {
    delete (window as any).location
    const url = new URL("http://localhost:3001/")
    window.location = url as any
    window.history.replaceState = vi.fn((state, unused, nextUrl) => {
      const parsed = new URL(nextUrl, "http://localhost:3001")
      window.location.search = parsed.search
      window.location.pathname = parsed.pathname
      window.location.hash = parsed.hash
    })
  })

  it("adds job_id to address bar when entering detail view", () => {
    setDeepLinkParam("job_123")
    expect(window.history.replaceState).toHaveBeenCalledWith(null, "", "/?job_id=job_123")
    expect(window.location.search).toBe("?job_id=job_123")
  })

  it("updates job_id when navigating between jobs and does not duplicate state", () => {
    setDeepLinkParam("job_123")
    setDeepLinkParam("job_456")
    expect(window.location.search).toBe("?job_id=job_456")
  })

  it("is no-op if the same job_id is set again and no record_id exists", () => {
    setDeepLinkParam("job_123")
    const callCount = (window.history.replaceState as any).mock.calls.length
    setDeepLinkParam("job_123")
    expect((window.history.replaceState as any).mock.calls.length).toBe(callCount)
  })

  it("cleans up record_id even if job_id is already present", () => {
    const url = new URL("http://localhost:3001/?job_id=job_123&record_id=rec_old")
    window.location = url as any
    setDeepLinkParam("job_123")
    expect(window.location.search).toBe("?job_id=job_123")
  })

  it("removes job_id and record_id on back to list while preserving other params and hash", () => {
    const url = new URL("http://localhost:3001/?tab=active&job_id=job_123&record_id=rec_456#section-work")
    window.location = url as any
    clearDeepLinkParams()
    expect(window.history.replaceState).toHaveBeenCalledWith(null, "", "/?tab=active#section-work")
    expect(window.location.search).toBe("?tab=active")
    expect(window.location.hash).toBe("#section-work")
  })

  it("declaratively synchronizes URL on component view change and cleans up on exit", () => {
    function TestWorkspace() {
      const [currentView, setCurrentView] = useState<string>("immersive-list")
      const [selectedJob, setSelectedJob] = useState<{ id: string } | null>(null)

      const exitDetailView = () => {
        clearDeepLinkParams()
      }

      useEffect(() => {
        if (currentView === "immersive-detail" && selectedJob?.id) {
          setDeepLinkParam(selectedJob.id)
        }
      }, [currentView, selectedJob?.id])

      return (
        <div>
          <button
            onClick={() => {
              setSelectedJob({ id: "job_xyz" })
              setCurrentView("immersive-detail")
            }}
          >
            Enter Detail
          </button>
          <button
            onClick={() => {
              exitDetailView()
              setCurrentView("immersive-list")
              setSelectedJob(null)
            }}
          >
            Exit Detail
          </button>
        </div>
      )
    }

    const { getByText } = render(<TestWorkspace />)
    expect(window.location.search).toBe("")

    fireEvent.click(getByText("Enter Detail"))
    expect(window.history.replaceState).toHaveBeenCalledWith(null, "", "/?job_id=job_xyz")
    expect(window.location.search).toBe("?job_id=job_xyz")

    fireEvent.click(getByText("Exit Detail"))
    expect(window.history.replaceState).toHaveBeenCalledWith(null, "", "/")
    expect(window.location.search).toBe("")
  })
})
