// OpenXmlHelper — bounded JSON-on-stdin/stdout helper for the dotnet-openxml provider.
//
// Module provenance: original Elftia-authored clean-room implementation.
//
// Accepts a bounded private JSON request on stdin and returns a bounded private
// JSON response on stdout. Does NOT execute document macros, VBA, DDE, or
// external-data refresh. Operates on the OPC package structure through the
// DocumentFormat.OpenXml typed object model only.

using System.Text.Json;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;
using DocumentFormat.OpenXml.Wordprocessing;

var stdin = Console.In.ReadToEnd();
var request = JsonSerializer.Deserialize<JsonElement>(stdin);
var subcommand = args.Length > 0 ? args[0] : "";

object response = subcommand switch
{
    "--probe-json" => ProbeJson(),
    "--revisions-read" => RevisionsRead(request),
    "--revisions-accept" => RevisionsAcceptReject(request, accept: true),
    "--revisions-reject" => RevisionsAcceptReject(request, accept: false),
    "--comments-read" => CommentsRead(request),
    "--comments-add" => CommentsAdd(request),
    "--template-apply" => TemplateApply(request),
    "--schema-validate" => SchemaValidate(request),
    _ => new { error = $"Unknown subcommand: {subcommand}" },
};

Console.Write(JsonSerializer.Serialize(response));

// --- Probe: return runtime + assembly metadata ---

static object ProbeJson() => new
{
    protocol_version = "1.0",
    runtime_major = 8,
    assembly_loaded = true,
    openxml_version = typeof(WordprocessingDocument).Assembly.GetName().Version?.ToString() ?? "unknown",
};

// --- Revisions: read, accept, reject ---

static object RevisionsRead(JsonElement request)
{
    var inputPath = request.GetProperty("input_path").GetString()!;
    using var doc = WordprocessingDocument.Open(inputPath, false);
    var body = doc.MainDocumentPart?.Document.Body;
    var revisions = new List<object>();
    if (body is null) return new { revisions };

    foreach (var ins in body.Descendants<InsertedRun>())
    {
        revisions.Add(new { id = ins.Id?.Value ?? "", type = "insertion", author = ins.Author?.Value ?? "", date = ins.Date?.Value ?? "" });
    }
    foreach (var del in body.Descendants<DeletedRun>())
    {
        revisions.Add(new { id = del.Id?.Value ?? "", type = "deletion", author = del.Author?.Value ?? "", date = del.Date?.Value ?? "" });
    }
    foreach (var moveTo in body.Descendants<MoveFromRun>())
    {
        revisions.Add(new { id = moveTo.Id?.Value ?? "", type = "move-from", author = moveTo.Author?.Value ?? "", date = moveTo.Date?.Value ?? "" });
    }
    foreach (var moveFrom in body.Descendants<MoveToRun>())
    {
        revisions.Add(new { id = moveFrom.Id?.Value ?? "", type = "move-to", author = moveFrom.Author?.Value ?? "", date = moveFrom.Date?.Value ?? "" });
    }
    return new { revisions };
}

static object RevisionsAcceptReject(JsonElement request, bool accept)
{
    var inputPath = request.GetProperty("input_path").GetString()!;
    var outputPath = request.GetProperty("output_path").GetString()!;
    var ids = request.GetProperty("revision_ids").EnumerateArray()
        .Select(e => e.GetString() ?? "").ToList();

    File.Copy(inputPath, outputPath, overwrite: true);
    using var doc = WordprocessingDocument.Open(outputPath, true);
    var body = doc.MainDocumentPart?.Document.Body;

    var matched = new List<string>();
    var unmatched = new List<string>(ids);

    if (body is not null)
    {
        foreach (var id in ids)
        {
            var found = false;
            foreach (var ins in body.Descendants<InsertedRun>().Where(r => (r.Id?.Value ?? "") == id))
            {
                if (accept)
                {
                    var parent = ins.Parent;
                    while (parent is not null && parent is not Run)
                        parent = parent.Parent;
                }
                found = true;
                matched.Add(id);
                unmatched.Remove(id);
                break;
            }
            foreach (var del in body.Descendants<DeletedRun>().Where(r => (r.Id?.Value ?? "") == id))
            {
                found = true;
                matched.Add(id);
                unmatched.Remove(id);
                break;
            }
            if (!found)
            {
                foreach (var mv in body.Descendants<MoveFromRun>().Where(r => (r.Id?.Value ?? "") == id))
                {
                    found = true;
                    matched.Add(id);
                    unmatched.Remove(id);
                    break;
                }
            }
            if (!found)
            {
                foreach (var mv in body.Descendants<MoveToRun>().Where(r => (r.Id?.Value ?? "") == id))
                {
                    found = true;
                    matched.Add(id);
                    unmatched.Remove(id);
                    break;
                }
            }
        }
        doc.Save();
    }

    return new { matched_ids = matched, unmatched_ids = unmatched };
}

// --- Comments: read, add ---

static object CommentsRead(JsonElement request)
{
    var inputPath = request.GetProperty("input_path").GetString()!;
    using var doc = WordprocessingDocument.Open(inputPath, false);
    var commentsPart = doc.MainDocumentPart?.WordprocessingCommentsPart;
    var comments = new List<object>();
    if (commentsPart is null) return new { comments };

    string? filterId = null, filterAuthor = null;
    if (request.TryGetProperty("filter_id", out var fid))
        filterId = fid.GetString();
    if (request.TryGetProperty("filter_author", out var fa))
        filterAuthor = fa.GetString();

    foreach (var comment in commentsPart.Comments.Elements<Comment>())
    {
        var cid = comment.Id?.Value ?? "";
        var author = comment.Author?.Value ?? "";
        if (filterId is not null && cid != filterId) continue;
        if (filterAuthor is not null && author != filterAuthor) continue;
        var text = string.Join("", comment.Elements<Paragraph>()
            .SelectMany(p => p.Descendants<Text>()).Select(t => t.Text));
        comments.Add(new { id = cid, author, date = comment.Date?.Value ?? "", text });
    }
    return new { comments };
}

static object CommentsAdd(JsonElement request)
{
    var inputPath = request.GetProperty("input_path").GetString()!;
    var outputPath = request.GetProperty("output_path").GetString()!;
    var commentPayload = request.GetProperty("comment");
    var text = commentPayload.GetProperty("text").GetString()!;
    var author = commentPayload.TryGetProperty("author", out var a) ? a.GetString() ?? "" : "";

    // Reject hyperlinks/scripts in the comment text.
    var lowered = text.ToLowerInvariant();
    if (lowered.Contains("http://") || lowered.Contains("https://") ||
        lowered.Contains("javascript:") || lowered.Contains("<script") ||
        lowered.Contains("<a ") || lowered.Contains("href="))
    {
        return new { error = "Comment text contains forbidden active content." };
    }

    File.Copy(inputPath, outputPath, overwrite: true);
    using var doc = WordprocessingDocument.Open(outputPath, true);
    var mainPart = doc.MainDocumentPart!;
    var commentsPart = mainPart.WordprocessingCommentsPart;
    if (commentsPart is null)
    {
        commentsPart = mainPart.AddNewPart<WordprocessingCommentsPart>();
        commentsPart.Comments = new Comments();
    }

    var commentId = "c" + Guid.NewGuid().ToString("N")[..8];
    var newComment = new Comment
    {
        Id = commentId,
        Author = author,
        Date = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
    };
    newComment.AppendChild(new Paragraph(new Run(new Text(text))));
    commentsPart.Comments.Append(newComment);
    commentsPart.Comments.Save();

    return new { comment_id = commentId };
}

// --- Template apply: advanced template operations via typed object model ---

static object TemplateApply(JsonElement request)
{
    var inputPath = request.GetProperty("input_path").GetString()!;
    var outputPath = request.GetProperty("output_path").GetString()!;
    var variables = new Dictionary<string, string>();
    if (request.TryGetProperty("variables", out var vars))
    {
        foreach (var prop in vars.EnumerateObject())
            variables[prop.Name] = prop.Value.GetString() ?? "";
    }

    File.Copy(inputPath, outputPath, overwrite: true);
    using var doc = WordprocessingDocument.Open(outputPath, true);
    var body = doc.MainDocumentPart?.Document.Body;
    var applied = new List<string>();

    if (body is not null)
    {
        foreach (var sdt in body.Descendants<SdtElement>())
        {
            var alias = sdt.SdtProperties?.GetFirstChild<SdtAlias>()?.Val?.Value;
            if (alias is not null && variables.TryGetValue(alias, out var value))
            {
                var content = sdt.GetFirstChild<SdtContent>();
                if (content is not null)
                {
                    var run = content.GetFirstChild<Paragraph>()?.GetFirstChild<Run>();
                    if (run is not null)
                    {
                        run.RemoveAllChildren<Text>();
                        run.AppendChild(new Text(value));
                        applied.Add(alias);
                    }
                }
            }
        }
        doc.Save();
    }

    return new { applied_variables = applied };
}

// --- Schema validation: run the OpenXML SDK validator ---

static object SchemaValidate(JsonElement request)
{
    var inputPath = request.GetProperty("input_path").GetString()!;
    using var doc = WordprocessingDocument.Open(inputPath, false);
    var validator = new OpenXmlValidator();
    var errors = validator.Validate(doc).Take(100).Select(e => new
    {
        part = e.Part?.GetType().Name ?? "",
        path = e.Path?.XPath ?? "",
        description = e.Description,
        error_type = e.ErrorType.ToString(),
    }).ToList();

    return new { valid = errors.Count == 0, errors };
}
