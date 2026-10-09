"""Bounded, label-free clip preprocessing; this is not an event model."""

import asyncio
from dataclasses import dataclass
import hashlib
import math
import re
from time import perf_counter

from app.models.media import MediaResolver
from app.schemas.model import EvidenceFrame, ModelInput, TemporalState


class IngestionError(ValueError):
    """Sanitized preprocessing failure. No decoder stderr or local paths escape."""


@dataclass(frozen=True)
class PreparedMedia:
    model_input: ModelInput
    resolver: MediaResolver
    clip_sha256: str
    frame_sha256: dict[str, str]
    extractor_version: str
    ffmpeg_version: str
    profile: dict
    preprocessing_ms: float


class MediaIngestion:
    """Read trusted clip bytes and select actual decoded frames on a fixed grid.

    Targets include the window start and exclude its end. A single decoded frame
    can cross several targets; it is emitted once and actual_frame_count records
    the resulting smaller count. Timestamps refer to the input stream PTS.
    """

    extractor_version = "ffmpeg-fixed-grid-v1"

    def __init__(
        self, resolver: MediaResolver, *, frame_count: int = 4,
        width: int = 640, height: int = 360,
        max_clip_bytes: int = 64 * 1024 * 1024,
        max_frame_bytes: int = 2 * 1024 * 1024,
        timeout_sec: float = 15.0, ffmpeg: str = "ffmpeg",
    ):
        limits = ((frame_count, 16), (width, 1920), (height, 1080),
                  (max_clip_bytes, 64 * 1024 * 1024),
                  (max_frame_bytes, 2 * 1024 * 1024))
        if any(type(value) is not int or not 1 <= value <= bound
               for value, bound in limits):
            raise ValueError("invalid preprocessing budget")
        if not math.isfinite(timeout_sec) or not 0 < timeout_sec <= 120:
            raise ValueError("timeout_sec must be finite and between 0 and 120")
        if not isinstance(ffmpeg, str) or not ffmpeg:
            raise ValueError("ffmpeg executable is required")
        self.resolver = resolver
        self.frame_count, self.width, self.height = frame_count, width, height
        self.max_clip_bytes, self.max_frame_bytes = max_clip_bytes, max_frame_bytes
        self.timeout_sec, self.ffmpeg = timeout_sec, ffmpeg

    async def prepare(self, model_input: ModelInput) -> PreparedMedia:
        started = perf_counter()
        try:
            return await asyncio.wait_for(self._prepare(model_input, started), self.timeout_sec)
        except asyncio.TimeoutError:
            raise IngestionError("media preprocessing timed out") from None
        except IngestionError:
            raise
        except (OSError, KeyError, ValueError, TypeError):
            raise IngestionError("invalid or unavailable input media") from None

    async def _prepare(self, model_input, started):
        # Revalidate even model_construct/model_copy inputs before building a command.
        mi = ModelInput.model_validate(model_input.model_dump(mode="python"))
        if not mi.clip_ref:
            raise IngestionError("clip_ref is required")
        clip = await asyncio.to_thread(
            self.resolver.read, mi.clip_ref, max_bytes=self.max_clip_bytes,
        )
        if not clip:
            raise IngestionError("empty input media")
        start, end = mi.window.start_ms / 1000, mi.window.end_ms / 1000
        targets = [start + (end - start) * i / self.frame_count
                   for i in range(self.frame_count)]
        crossings = "+".join(
            f"gte(t,{target:.9f})*(isnan(prev_selected_t)+lt(prev_selected_t,{target:.9f}))"
            for target in targets
        )
        filters = (
            f"select='between(t,{start:.9f},{end:.9f})*({crossings})',"
            f"showinfo,scale={self.width}:{self.height}:flags=bilinear"
        )
        # Only pipe input is permitted: no filenames, network protocols or playlists.
        args = [self.ffmpeg, "-nostdin", "-loglevel", "info", "-max_alloc", "67108864",
                "-threads", "1", "-copyts", "-protocol_whitelist", "pipe",
                "-i", "pipe:0", "-map", "0:v:0", "-an", "-sn", "-dn",
                "-filter_threads", "1", "-vf", filters,
                "-frames:v", str(self.frame_count), "-fps_mode", "passthrough",
                "-c:v", "mjpeg", "-threads:v", "1", "-q:v", "2",
                "-f", "image2pipe", "pipe:1"]
        output, stderr = await self._decode(args, clip)
        frames = self._jpeg_frames(output)
        pts = [(int(index), float(value)) for index, value in re.findall(
            rb"\bn:\s*(\d+)\s+pts:.*?\bpts_time:([\d.eE+\-]+)", stderr,
        )]
        if not frames or len(frames) != len(pts) or len(frames) > self.frame_count:
            raise IngestionError("decoded frame provenance is invalid")
        timestamps = []
        for expected_index, (actual_index, seconds) in enumerate(pts):
            if actual_index != expected_index or not math.isfinite(seconds) or not start <= seconds <= end:
                raise IngestionError("decoded timestamp is outside the input window")
            timestamps.append(round(seconds * 1000))
        if len(set(timestamps)) != len(timestamps) or timestamps != sorted(timestamps):
            raise IngestionError("decoded timestamps are ambiguous")
        version_match = re.search(rb"^ffmpeg version (\S+)", stderr, re.MULTILINE)
        if version_match is None:
            raise IngestionError("decoder version is unavailable")
        clip_hash = (await asyncio.to_thread(hashlib.sha256, clip)).hexdigest()
        assets, evidence, frame_hashes = {}, [], {}
        for timestamp, frame in zip(timestamps, frames):
            digest = (await asyncio.to_thread(hashlib.sha256, frame)).hexdigest()
            # Opaque IDs encode content provenance, never filenames or sample labels.
            identity = hashlib.sha256(f"{clip_hash}:{timestamp}:{digest}".encode()).hexdigest()
            frame_id, token = f"frame_{identity}", f"media_{identity}"
            evidence.append(EvidenceFrame(frame_id=frame_id, timestamp_ms=timestamp, media_ref=token))
            assets[token], frame_hashes[frame_id] = frame, digest
        rebuilt = ModelInput.model_validate({
            **mi.model_dump(mode="python"), "evidence": evidence,
            "temporal_state": TemporalState(),
        })
        profile = {
            "frame_count": self.frame_count, "actual_frame_count": len(frames),
            "width": self.width, "height": self.height,
            "max_clip_bytes": self.max_clip_bytes, "max_frame_bytes": self.max_frame_bytes,
            "timeout_sec": self.timeout_sec, "decoder_threads": 1, "encoder_threads": 1,
            "sampling": "first-decoded-at-or-after-fixed-grid-v1",
            "timestamp_basis": "input-stream-pts", "targets_ms": [t * 1000 for t in targets],
            "actual_pts_ms": [seconds * 1000 for _, seconds in pts],
            "timestamp_quantization": "nearest-millisecond",
            "duplicate_target_policy": "emit-actual-frame-once",
            "sparse_coverage": len(frames) < self.frame_count,
        }
        return PreparedMedia(
            rebuilt, self.resolver.with_assets(assets), clip_hash, frame_hashes,
            self.extractor_version, version_match.group(1).decode("ascii", errors="replace"),
            profile, (perf_counter() - started) * 1000,
        )

    async def _decode(self, args, clip):
        process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def bounded_read(stream, budget):
            chunks, size = [], 0
            while chunk := await stream.read(min(65536, budget - size + 1)):
                size += len(chunk)
                if size > budget:
                    raise IngestionError("decoder output exceeds byte budget")
                chunks.append(chunk)
            return b"".join(chunks)

        async def feed():
            try:
                for offset in range(0, len(clip), 65536):
                    process.stdin.write(clip[offset:offset + 65536])
                    await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        tasks = [asyncio.create_task(feed()),
                 asyncio.create_task(bounded_read(process.stdout, self.frame_count * self.max_frame_bytes)),
                 asyncio.create_task(bounded_read(process.stderr, 256 * 1024))]
        try:
            _, stdout, stderr = await asyncio.gather(*tasks)
            if await process.wait() != 0:
                raise IngestionError("media decoding failed")
            return stdout, stderr
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await process.wait()

    def _jpeg_frames(self, data):
        frames, offset = [], 0
        while offset < len(data):
            if data[offset:offset + 2] != b"\xff\xd8":
                raise IngestionError("decoder output is not JPEG")
            end = data.find(b"\xff\xd9", offset + 2)
            if end < 0:
                raise IngestionError("incomplete decoded JPEG")
            frame = data[offset:end + 2]
            if len(frame) > self.max_frame_bytes:
                raise IngestionError("decoded frame exceeds byte budget")
            frames.append(frame)
            offset = end + 2
        return frames
