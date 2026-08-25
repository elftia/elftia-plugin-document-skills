// OpenXmlHelper — bounded JSON-on-stdin/stdout helper for the dotnet-openxml provider.
//
// Module provenance: original Elftia-authored clean-room implementation.
//
// Accepts a bounded private JSON request on stdin and returns a bounded private
// JSON response on stdout. Does NOT execute document macros, VBA, DDE, or
// external-data refresh. Operates on the OPC package structure through the
// DocumentFormat.OpenXml typed object model only.

using System.Globalization;
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
    "--comments-read" => CommentsOperations.Read(request),
    "--comments-add" => CommentsOperations.Add(request),
    "--comments-resolve" => CommentsOperations.Resolve(request),
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
    var maxRevisions = request.TryGetProperty("max_revisions", out var maximum)
        && maximum.TryGetInt32(out var requestedMaximum)
        ? Math.Clamp(requestedMaximum, 1, 10_001)
        : 10_000;
    using var doc = WordprocessingDocument.Open(inputPath, false);
    var body = doc.MainDocumentPart?.Document.Body;
    var revisions = new List<object>();
    if (body is null) return new { revisions };
    var paragraphs = body.Descendants<Paragraph>().ToList();
    var paragraphIndexes = paragraphs.Select((item, index) => (item, index))
        .ToDictionary(pair => pair.item, pair => pair.index);
    var tables = body.Descendants<Table>().ToList();
    var tableIndexes = tables.Select((item, index) => (item, index))
        .ToDictionary(pair => pair.item, pair => pair.index);
    var filters = request.TryGetProperty("filters", out var filterPayload)
        ? filterPayload
        : default;
    var authors = filters.ValueKind == JsonValueKind.Object
        ? ReadStringSet(filters, "authors")
        : null;
    var types = filters.ValueKind == JsonValueKind.Object
        ? ReadStringSet(filters, "types")
        : null;
    var dateFrom = filters.ValueKind == JsonValueKind.Object
        ? ReadRevisionDate(filters, "date_from")
        : null;
    var dateTo = filters.ValueKind == JsonValueKind.Object
        ? ReadRevisionDate(filters, "date_to")
        : null;
    var revisionIds = request.TryGetProperty("revision_ids", out var idPayload)
        ? idPayload.EnumerateArray().Select(item => item.GetString() ?? "")
            .ToHashSet(StringComparer.Ordinal)
        : null;
    var scope = request.TryGetProperty("scope", out var scopePayload)
        ? scopePayload
        : default;
    var scopeRange = scope.ValueKind == JsonValueKind.Object
        ? scope.GetProperty("range").GetString()
        : null;
    int? scopeIndex = scopeRange switch
    {
        "paragraph" => scope.GetProperty("paragraph_index").GetInt32(),
        "table" => scope.GetProperty("table_index").GetInt32(),
        null => null,
        _ => throw new InvalidOperationException("Unsupported revision scope."),
    };

    foreach (var revision in CollectRevisions(body))
    {
        if (revisionIds is not null && !revisionIds.Contains(revision.Id)) continue;
        if (authors is not null && !authors.Contains(revision.Author)) continue;
        if (types is not null && !types.Contains(revision.Type)) continue;
        var revisionDate = revision.Date?.Value.ToUniversalTime();
        if (dateFrom is not null && (revisionDate is null || revisionDate < dateFrom)) continue;
        if (dateTo is not null && (revisionDate is null || revisionDate > dateTo)) continue;
        var paragraph = revision.Element.Ancestors<Paragraph>().FirstOrDefault();
        var paragraphIndex = paragraph is not null
            && paragraphIndexes.TryGetValue(paragraph, out var resolvedParagraph)
            ? resolvedParagraph
            : -1;
        var table = revision.Element.Ancestors<Table>().FirstOrDefault();
        int? tableIndex = table is not null
            && tableIndexes.TryGetValue(table, out var resolvedTable)
            ? resolvedTable
            : null;
        if (scopeRange == "paragraph" && paragraphIndex != scopeIndex) continue;
        if (scopeRange == "table" && tableIndex != scopeIndex) continue;
        revisions.Add(new
        {
            id = revision.Id,
            type = revision.Type,
            author = revision.Author,
            date = FormatDate(revision.Date),
            location = new
            {
                story = "body",
                paragraph_index = paragraphIndex,
                table_index = tableIndex,
            },
        });
        if (revisions.Count >= maxRevisions) break;
    }
    return new { revisions };
}

static object RevisionsAcceptReject(JsonElement request, bool accept)
{
    var inputPath = request.GetProperty("input_path").GetString()!;
    var outputPath = request.GetProperty("output_path").GetString()!;
    var requestedIds = request.GetProperty("revision_ids").EnumerateArray()
        .Select(e => e.GetString() ?? "").Distinct().ToList();

    File.Copy(inputPath, outputPath, overwrite: true);
    using var doc = WordprocessingDocument.Open(outputPath, true);
    var body = doc.MainDocumentPart?.Document.Body;

    var matched = new List<string>();
    var unmatched = new List<string>();

    if (body is not null)
    {
        var revisions = CollectRevisions(body);
        var ids = requestedIds.Count > 0
            ? requestedIds
            : revisions.Select(item => item.Id).Where(id => id.Length > 0).Distinct().Take(1_001).ToList();
        if (ids.Count > 1_000)
        {
            throw new InvalidOperationException("Revision transaction exceeds the 1000-id bound.");
        }
        foreach (var id in ids)
        {
            var targets = revisions.Where(item => item.Id == id).ToList();
            if (targets.Count == 0)
            {
                unmatched.Add(id);
                continue;
            }
            foreach (var target in targets)
            {
                ApplyRevision(target, accept);
            }
            matched.Add(id);
        }
        doc.MainDocumentPart!.Document.Save();
    }
    else
    {
        unmatched.AddRange(requestedIds);
    }

    return new { matched_ids = matched, unmatched_ids = unmatched };
}

static void ApplyRevision(
    RevisionItem revision,
    bool accept)
{
    if (revision.Element.Parent is null) return;
    var keepContents = revision.Type switch
    {
        "insertion" => accept,
        "deletion" => !accept,
        "move-from" => !accept,
        "move-to" => accept,
        _ => false,
    };
    if (!keepContents)
    {
        revision.Element.Remove();
        return;
    }
    foreach (var child in revision.Element.ChildElements.ToList())
    {
        child.Remove();
        if (revision.Type == "deletion")
        {
            foreach (var deletedText in child.Descendants<DeletedText>().ToList())
            {
                var restored = new Text(deletedText.Text) { Space = deletedText.Space };
                deletedText.InsertAfterSelf(restored);
                deletedText.Remove();
            }
        }
        revision.Element.InsertBeforeSelf(child);
    }
    revision.Element.Remove();
}

static List<RevisionItem> CollectRevisions(Body body)
{
    var revisions = new List<RevisionItem>();
    foreach (var element in body.Descendants())
    {
        switch (element)
        {
            case InsertedRun inserted:
                revisions.Add(new RevisionItem(
                    inserted.Id?.Value ?? "",
                    "insertion",
                    inserted.Author?.Value ?? "",
                    inserted.Date,
                    inserted));
                break;
            case DeletedRun deleted:
                revisions.Add(new RevisionItem(
                    deleted.Id?.Value ?? "",
                    "deletion",
                    deleted.Author?.Value ?? "",
                    deleted.Date,
                    deleted));
                break;
            case MoveFromRun moveFrom:
                revisions.Add(new RevisionItem(
                    moveFrom.Id?.Value ?? "",
                    "move-from",
                    moveFrom.Author?.Value ?? "",
                    moveFrom.Date,
                    moveFrom));
                break;
            case MoveToRun moveTo:
                revisions.Add(new RevisionItem(
                    moveTo.Id?.Value ?? "",
                    "move-to",
                    moveTo.Author?.Value ?? "",
                    moveTo.Date,
                    moveTo));
                break;
        }
    }
    return revisions;
}

static HashSet<string>? ReadStringSet(JsonElement parent, string property)
{
    return parent.TryGetProperty(property, out var payload)
        ? payload.EnumerateArray().Select(item => item.GetString() ?? "")
            .ToHashSet(StringComparer.Ordinal)
        : null;
}

static DateTime? ReadRevisionDate(JsonElement parent, string property)
{
    if (!parent.TryGetProperty(property, out var payload)) return null;
    if (!DateTime.TryParseExact(
        payload.GetString(),
        "yyyy-MM-ddTHH:mm:ssZ",
        CultureInfo.InvariantCulture,
        DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
        out var parsed))
    {
        throw new InvalidOperationException("Invalid revision date filter.");
    }
    return parsed;
}

static string FormatDate(DateTimeValue? value) => value?.Value is DateTime date
    ? date.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    : "";

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
                var run = sdt.Descendants<Run>().FirstOrDefault();
                if (run is not null)
                {
                    run.RemoveAllChildren<Text>();
                    run.AppendChild(new Text(value));
                    applied.Add(alias);
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
    var maxErrors = request.TryGetProperty("max_errors", out var maximum)
        && maximum.TryGetInt32(out var requestedMaximum)
        ? Math.Clamp(requestedMaximum, 1, 1_001)
        : 100;
    using var doc = WordprocessingDocument.Open(inputPath, false);
    var validator = new OpenXmlValidator();
    var errors = validator.Validate(doc).Take(maxErrors).Select(e => new
    {
        part = e.Part?.GetType().Name ?? "",
        path = e.Path?.XPath ?? "",
        description = e.Description,
        error_type = e.ErrorType.ToString(),
    }).ToList();

    return new { valid = errors.Count == 0, errors };
}

sealed record RevisionItem(
    string Id,
    string Type,
    string Author,
    DateTimeValue? Date,
    OpenXmlElement Element);
